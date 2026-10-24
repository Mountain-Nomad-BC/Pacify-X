'use strict';
const crypto=require('node:crypto');
const {performance}=require('node:perf_hooks');

async function executeAdmittedHostModel({vscode,prepared,token,assertCurrent,attestHostToolInterface,enforceAdmittedHostToolPolicy}) {
  if(typeof assertCurrent !== 'function')throw new Error('native-host-currentness-required');
  const checkCurrent=async()=>{
    if(token?.isCancellationRequested)throw new Error('host-model-cancelled');
    await assertCurrent();
    if(token?.isCancellationRequested)throw new Error('host-model-cancelled');
  };
  await checkCurrent();
  if (!vscode.lm?.selectChatModels) throw new Error('VS Code Language Model API is unavailable in this host.');
  const route = prepared?.record?.model || prepared?.model || {};
  const selector = {};
  if (route.vendor && route.vendor !== 'auto') selector.vendor = String(route.vendor);
  if (route.family && route.family !== 'auto') selector.family = String(route.family);
  if (route.model_id && route.model_id !== 'auto') selector.id = String(route.model_id);
  if (route.version && route.version !== 'auto') selector.version = String(route.version);
  if (!selector.id) throw new Error('An exact admitted VS Code model ID is required; automatic model substitution is refused.');
  if (route.provider === 'pacify-local' && selector.vendor !== 'pacify-local') throw new Error('Pacify local routes must bind vendor pacify-local exactly.');
  await checkCurrent();
  const models = await vscode.lm.selectChatModels(selector);
  await checkCurrent();
  if (!models.length) throw new Error(`No VS Code language model matches ${JSON.stringify(selector)}.`);
  if(models.length !== 1)throw new Error('exact-host-model-selection-ambiguous');
  const model = models[0];
  for (const [field, actual] of [['id', model.id], ['vendor', model.vendor], ['family', model.family], ['version', model.version]]) {
    if (selector[field] && String(selector[field]) !== String(actual)) throw new Error(`VS Code returned ${field} ${actual} for the exact admitted ${field} ${selector[field]}; model substitution is refused.`);
  }
  const instructions = String(prepared?.record?.instructions || prepared?.instructions || '').trim();
  const task = prepared?.record?.task || prepared?.task || {};
  const outputSchema = prepared?.record?.output_schema || prepared?.output_schema || { type: 'object', additionalProperties: true };
  const prompt = [
    instructions,
    'Execute only the bounded task below. Do not expand authority, scope, tools, or effects.',
    `Task JSON:\n${JSON.stringify(task, null, 2)}`,
    `Return one JSON object matching this output schema:\n${JSON.stringify(outputSchema, null, 2)}`
  ].filter(Boolean).join('\n\n');
  const messages = [vscode.LanguageModelChatMessage.User(prompt)];
  await checkCurrent();
  const inputTokens = await model.countTokens(prompt, token);
  if(!Number.isSafeInteger(inputTokens) || inputTokens < 0)throw new Error('host-input-token-count-invalid');
  await checkCurrent();
  if (Number.isFinite(model.maxInputTokens) && inputTokens > model.maxInputTokens) throw new Error(`Agent prompt requires ${inputTokens} tokens but the selected model accepts ${model.maxInputTokens}.`);
  const declaredOutput=Number(route.max_output_tokens || 4096);
  if(!Number.isSafeInteger(declaredOutput) || declaredOutput < 1 || declaredOutput > 32768)throw new Error('host-output-token-budget-invalid');
  const requestedModelOptions = { maxOutputTokens: Number(route.max_output_tokens || 4096), temperature: Number(route.temperature || 0) };
  const requestOptions = { justification: `Run admitted Pacify-X agent ${prepared?.record?.agent_id || prepared?.agent_id || ''}`, modelOptions: requestedModelOptions };
  const admittedHostTools = Array.isArray(prepared?.record?.host_tools || prepared?.host_tools) ? (prepared?.record?.host_tools || prepared?.host_tools) : [];
  const registeredTools = new Map((vscode.lm?.tools || []).map(tool => [tool.name, tool]));
  const missingTools = admittedHostTools.filter(binding => !registeredTools.has(binding.name)).map(binding => binding.name);
  if (missingTools.length) throw new Error(`Admitted agent tools are unavailable in this host: ${missingTools.join(', ')}.`);
  const liveToolInterfaces = new Map(admittedHostTools.map(binding => [binding.name, attestHostToolInterface(registeredTools.get(binding.name), binding.name)]));
  if (admittedHostTools.length) {
    if (route.provider === 'pacify-local') throw new Error('The selected local model route does not support tool calling.');
    requestOptions.tools = admittedHostTools.map(binding => {
      const tool = registeredTools.get(binding.name);
      return { name: tool.name, description: tool.description, inputSchema: tool.inputSchema };
    });
    requestOptions.toolMode = vscode.LanguageModelChatToolMode.Auto;
  }
  let text = ''; let streamedText = ''; const toolsDispatched = []; let toolCalls = 0; let outputTokens = 0; let aggregateInputTokens = 0;
  const outputTokenLimit = Math.max(1, Math.min(32768, Number(route.max_output_tokens || 4096)));
  const aggregateInputTokenLimit = Math.max(inputTokens, Math.min(1_000_000, Number(route.max_total_input_tokens || model.maxInputTokens || Math.max(8192, inputTokens * 4))));
  const deadlineMs = Math.max(10_000, Math.min(300_000, Number(route.timeout_seconds || 120) * 1000));
  const started = performance.now();
  const requestCancellation = new vscode.CancellationTokenSource();
  const linkedCancellation = token?.onCancellationRequested(() => requestCancellation.cancel());
  const deadline = setTimeout(() => requestCancellation.cancel(), deadlineMs);
  let primary=null;
  try { while (true) {
    await checkCurrent();
    if(requestCancellation.token.isCancellationRequested)throw new Error('host-model-cancelled');
    if (performance.now() - started >= deadlineMs) throw new Error(`Agent model request exceeded the admitted ${deadlineMs} ms wall-time budget.`);
    const roundInputTokens = (await Promise.all(messages.map(message => model.countTokens(message, requestCancellation.token)))).reduce((sum, count) => sum + count, 0);
    if(!Number.isSafeInteger(roundInputTokens) || roundInputTokens < 0)throw new Error('host-input-token-count-invalid');
    aggregateInputTokens += roundInputTokens;
    if (aggregateInputTokens > aggregateInputTokenLimit) throw new Error(`Agent conversation exceeded the admitted ${aggregateInputTokenLimit}-token aggregate input budget.`);
    if (Number.isFinite(model.maxInputTokens) && roundInputTokens > model.maxInputTokens) throw new Error(`Agent conversation requires ${roundInputTokens} tokens but the selected model accepts ${model.maxInputTokens}.`);
    await checkCurrent();
    const response = await model.sendRequest(messages, requestOptions, requestCancellation.token);
    const responseParts = []; const calls = []; let responseText = '';
    for await (const part of response.stream) {
      await checkCurrent();
      if(requestCancellation.token.isCancellationRequested)throw new Error('host-model-cancelled');
      if (part instanceof vscode.LanguageModelTextPart) {
        responseText += part.value; streamedText += part.value; responseParts.push(part);
        if(Buffer.byteLength(streamedText) > 131072)throw new Error('host-output-byte-limit');
      } else if (part instanceof vscode.LanguageModelToolCallPart) {
        calls.push(part); responseParts.push(part);
      }
    }
    await checkCurrent();
    const roundOutputTokens=await model.countTokens(responseText, requestCancellation.token);
    if(!Number.isSafeInteger(roundOutputTokens) || roundOutputTokens < 0)throw new Error('host-output-token-count-invalid');
    outputTokens += roundOutputTokens;
    if (outputTokens > outputTokenLimit) throw new Error(`Agent model output exceeded the admitted ${outputTokenLimit}-token budget.`);
    if (!calls.length) { text += responseText; break; }
    if (toolCalls + calls.length > 8) throw new Error('Agent exceeded the admitted eight-call tool budget.');
    messages.push(vscode.LanguageModelChatMessage.Assistant(responseParts));
    const resultParts = [];
    for (const call of calls) {
      const admitted = admittedHostTools.find(binding => binding.name === call.name);
      if (!admitted) throw new Error(`Model requested an unbound tool: ${call.name}.`);
      const policy = enforceAdmittedHostToolPolicy(admitted, call.input);
      const toolReceipt = { call_id: call.callId, name: call.name, binding_id: admitted.binding_id, binding_sha256: admitted.binding_sha256, host_tool_interface_sha256: liveToolInterfaces.get(call.name), input_sha256: crypto.createHash('sha256').update(JSON.stringify(policy.sanitized_input || {})).digest('hex'), result_sha256: null, effect_grant_ids: admitted.effect_grant_ids || [], effects: policy.effects, scope_roots: policy.scope_roots, validated_targets: policy.validated_targets, status: 'started' };
      toolsDispatched.push(toolReceipt);
      let result;
      try {
        await checkCurrent();
        result = await vscode.lm.invokeTool(call.name, {
          input: policy.sanitized_input,
          toolInvocationToken: undefined,
          tokenizationOptions: { tokenBudget: Math.max(1, Math.min(4096, outputTokenLimit - outputTokens)), countTokens: (value, countToken) => model.countTokens(value, countToken) }
        }, requestCancellation.token);
      } catch (error) {
        toolReceipt.status = 'failed'; toolReceipt.error_code = error?.name || 'ToolInvocationError'; throw error;
      }
      await checkCurrent();
      resultParts.push(new vscode.LanguageModelToolResultPart(call.callId, result.content));
      const resultJson = JSON.stringify(result.content || []);
      toolReceipt.result_sha256 = crypto.createHash('sha256').update(resultJson).digest('hex'); toolReceipt.status = 'completed';
      toolCalls += 1;
    }
    messages.push(vscode.LanguageModelChatMessage.User(resultParts));
  }} catch (error) { primary=error;try{error.pxToolsDispatched=toolsDispatched;}catch{}throw error; } finally {
    clearTimeout(deadline);const cleanup=[];
    for(const release of [()=>linkedCancellation?.dispose(),()=>requestCancellation.dispose()])try{release();}catch(error){cleanup.push(error);}
    if(cleanup.length){if(!primary)throw new AggregateError(cleanup,'host-cancellation-custody-uncertain');try{primary.custodyCleanupErrors=cleanup;}catch{}}
  }
  await checkCurrent();
  if (!text.trim()) throw new Error('The selected language model returned an empty response.');
  let output;
  try { output = JSON.parse(text); }
  catch { output = { text }; }
  if (!output || Array.isArray(output) || typeof output !== 'object') output = { value: output };
  return {
    status: 'completed',
    output,
    model: { id: model.id, family: model.family, vendor: model.vendor, version: model.version, initial_input_tokens: inputTokens, aggregate_input_tokens: aggregateInputTokens, aggregate_input_token_limit: aggregateInputTokenLimit, output_tokens: outputTokens, output_token_limit: outputTokenLimit, streamed_characters: streamedText.length, requested_model_options: requestedModelOptions, wall_time_ms: Math.round(performance.now() - started) },
    tools_dispatched: toolsDispatched
  };
}

module.exports={executeAdmittedHostModel};
