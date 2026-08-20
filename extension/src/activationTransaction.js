'use strict';

class ActivationTransaction {
  constructor(context, options = {}) {
    if (!Array.isArray(context?.subscriptions)) throw new Error('activation-context-subscriptions-required');
    this.context = context;
    this.faultInjector = options.faultInjector;
    this.pending = [];
    this.committed = false;
    this.rolledBack = false;
  }

  own(...disposables) {
    if (this.rolledBack) throw new Error('activation-transaction-rolled-back');
    for (const disposable of disposables) {
      if (!disposable || typeof disposable.dispose !== 'function') throw new Error('activation-disposable-required');
      this.context.subscriptions.push(disposable);
      if (!this.committed) this.pending.push(disposable);
      this.faultInjector?.({ registered: this.pending.length });
    }
    return disposables.length === 1 ? disposables[0] : disposables;
  }

  commit() {
    if (this.rolledBack) throw new Error('activation-transaction-rolled-back');
    this.committed = true;
    this.pending.length = 0;
  }

  rollback() {
    if (this.committed || this.rolledBack) return;
    this.rolledBack = true;
    const owned = new Set(this.pending);
    for (const disposable of [...this.pending].reverse()) {
      try { disposable.dispose(); } catch {}
    }
    this.context.subscriptions.splice(0, this.context.subscriptions.length,
      ...this.context.subscriptions.filter(item => !owned.has(item)));
    this.pending.length = 0;
  }
}

module.exports = { ActivationTransaction };
