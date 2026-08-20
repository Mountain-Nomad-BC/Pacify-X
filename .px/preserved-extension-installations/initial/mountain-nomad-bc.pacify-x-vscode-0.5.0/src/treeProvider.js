'use strict';

class ControlCenterTreeProvider {
  constructor(vscode) {
    this.vscode = vscode;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
    this.snapshot = undefined;
  }

  setSnapshot(snapshot) {
    this.snapshot = snapshot;
    this.emitter.fire(undefined);
  }

  getTreeItem(item) { return item; }

  getChildren() {
    const vscode = this.vscode;
    if (!this.snapshot) return [this.item('Open Pacify-X Control Plane', 'dashboard', 'pacifyX.openDashboard')];
    const s = this.snapshot;
    return [
      this.item(s.connected ? `${s.project.name} · connected` : 'Engine disconnected', s.connected ? 'pass-filled' : 'warning'),
      this.item(`${s.counts?.skills ?? 0} skills · ${s.counts?.tools ?? 0} tools`, 'tools'),
      this.item(`${s.counts?.agents ?? 0} agents · ${s.counts?.workflows ?? 0} workflows`, 'organization'),
      this.item(`${s.attention?.length ?? 0} attention items`, s.attention?.length ? 'bell-dot' : 'check'),
      this.item('Open Control Plane', 'dashboard', 'pacifyX.openDashboard'),
      this.item('Validate Control Plane', 'verified-filled', 'pacifyX.validateControlPlane')
    ];
  }

  item(label, icon, command) {
    const item = new this.vscode.TreeItem(label, this.vscode.TreeItemCollapsibleState.None);
    item.iconPath = new this.vscode.ThemeIcon(icon);
    if (command) item.command = { command, title: label };
    return item;
  }
}

module.exports = { ControlCenterTreeProvider };
