import * as vscode from "vscode";
import { execFile } from "node:child_process";
import * as path from "node:path";

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("AI Agent Starter");
  context.subscriptions.push(output);

  const openDashboardCommand = vscode.commands.registerCommand(
    "aiAgentStarter.openDashboard",
    async () => {
      const panel = vscode.window.createWebviewPanel(
        "aiAgentStarterDashboard",
        "AI Agent Starter Chat",
        vscode.ViewColumn.One,
        {
          enableScripts: true,
          localResourceRoots: [
            vscode.Uri.joinPath(context.extensionUri, "media")
          ]
        }
      );

      const logoUri = panel.webview.asWebviewUri(
        vscode.Uri.joinPath(context.extensionUri, "media", "logo.png")
      );

      panel.webview.html = getChatLikeHtml(panel.webview, logoUri.toString());

      panel.webview.onDidReceiveMessage(async (message: WebviewMessage) => {
        if (message.type === "sendMessage") {
          const bridgeResult = await runPythonChatBridge(context.extensionUri, {
            text: message.text,
            mode: message.mode,
            backend: message.backend,
            attachments: message.attachments
          });

          const reply = bridgeResult.ok
            ? (bridgeResult.text ?? "")
            : (`[error] ${bridgeResult.error ?? "unknown bridge error"}`);

          panel.webview.postMessage({
            type: "assistantReply",
            text: reply
          });
          return;
        }

        if (message.type === "attachRequested") {
          const files = await vscode.window.showOpenDialog({
            canSelectFiles: true,
            canSelectFolders: false,
            canSelectMany: false,
            openLabel: "Attach"
          });
          if (files && files.length > 0) {
            panel.webview.postMessage({
              type: "attachmentAdded",
              fileName: files[0].path.split("/").pop() ?? files[0].fsPath
            });
          }
          return;
        }

        if (message.type === "runDiagnostics") {
          await vscode.commands.executeCommand("aiAgentStarter.showDiagnostics");
          return;
        }

        if (message.type === "openWizard") {
          await vscode.commands.executeCommand("aiAgentStarter.createProjectWizard");
          return;
        }
      });
    }
  );

  const showDiagnosticsCommand = vscode.commands.registerCommand(
    "aiAgentStarter.showDiagnostics",
    async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showInformationMessage("No active editor found.");
        return;
      }

      const uri = editor.document.uri;
      const diagnostics = vscode.languages.getDiagnostics(uri);
      const relativePath = vscode.workspace.asRelativePath(uri);

      output.clear();
      output.appendLine(`Diagnostics for ${relativePath}`);
      output.appendLine("-".repeat(60));

      if (diagnostics.length === 0) {
        output.appendLine("No diagnostics found.");
        output.show(true);
        vscode.window.showInformationMessage("No diagnostics found in active file.");
        return;
      }

      diagnostics.forEach((d: vscode.Diagnostic, index: number) => {
        const sev = severityToText(d.severity);
        const line = d.range.start.line + 1;
        const col = d.range.start.character + 1;
        output.appendLine(
          `${index + 1}. [${sev}] ${line}:${col} - ${d.message}`
        );
      });

      output.show(true);
      vscode.window.showInformationMessage(
        `Found ${diagnostics.length} diagnostics in active file.`
      );
    }
  );

  const insertBoilerplateCommand = vscode.commands.registerCommand(
    "aiAgentStarter.insertBoilerplate",
    async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showInformationMessage("No active editor found.");
        return;
      }

      const snippet = new vscode.SnippetString(
        [
          "export function ${1:handler}(input: ${2:string}): ${3:string} {",
          "  if (!input) {",
          "    throw new Error(\"input is required\");",
          "  }",
          "",
          "  return input.trim();",
          "}",
          ""
        ].join("\n")
      );

      await editor.insertSnippet(snippet);
    }
  );

  const createProjectWizardCommand = vscode.commands.registerCommand(
    "aiAgentStarter.createProjectWizard",
    async () => {
      const template = await vscode.window.showQuickPick(
        [
          {
            label: "React + TypeScript",
            detail: "Vite-style minimal React app",
            value: "react"
          },
          {
            label: "Node.js + TypeScript",
            detail: "CLI-ready Node project",
            value: "node"
          },
          {
            label: "Python",
            detail: "Simple app + tests + requirements",
            value: "python"
          }
        ],
        {
          title: "Project Wizard: Choose Template",
          placeHolder: "Select project template"
        }
      );

      if (!template) {
        return;
      }

      const projectName = await vscode.window.showInputBox({
        title: "Project Wizard: Project Name",
        prompt: "Enter a folder name for the new project",
        value: template.value === "react" ? "my-react-app" : template.value === "node" ? "my-node-app" : "my-python-app",
        validateInput: (value: string) => {
          if (!value.trim()) {
            return "Project name is required.";
          }
          if (/[\\/:*?"<>|]/.test(value)) {
            return "Project name contains invalid path characters.";
          }
          return undefined;
        }
      });

      if (!projectName) {
        return;
      }

      const targetRootSelection = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: "Select parent folder"
      });

      if (!targetRootSelection || targetRootSelection.length === 0) {
        return;
      }

      const parentUri = targetRootSelection[0];
      const projectUri = vscode.Uri.joinPath(parentUri, projectName.trim());

      const exists = await pathExists(projectUri);
      if (exists) {
        vscode.window.showErrorMessage("Target folder already exists. Please choose a different project name.");
        return;
      }

      const files =
        template.value === "react"
          ? buildReactTemplate(projectName.trim())
          : template.value === "node"
            ? buildNodeTemplate(projectName.trim())
            : buildPythonTemplate(projectName.trim());

      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `Creating ${template.label} project...`,
          cancellable: false
        },
        async (progress: vscode.Progress<{ message?: string; increment?: number }>) => {
          progress.report({ increment: 10, message: "Preparing folders" });
          await vscode.workspace.fs.createDirectory(projectUri);
          progress.report({ increment: 20, message: "Writing project files" });
          await writeTemplateFiles(projectUri, files);
          progress.report({ increment: 70, message: "Done" });
        }
      );

      output.appendLine(`[wizard] Created ${template.value} project at ${projectUri.fsPath}`);

      const openNow = await vscode.window.showInformationMessage(
        `Project created: ${projectName}`,
        "Open Project",
        "Copy Path"
      );

      if (openNow === "Open Project") {
        await vscode.commands.executeCommand("vscode.openFolder", projectUri, true);
        return;
      }

      if (openNow === "Copy Path") {
        await vscode.env.clipboard.writeText(projectUri.fsPath);
        vscode.window.showInformationMessage("Project path copied to clipboard.");
      }
    }
  );

  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusBar.text = "$(rocket) AI Starter";
  statusBar.tooltip = "Open AI Agent Starter Dashboard";
  statusBar.command = "aiAgentStarter.openDashboard";
  statusBar.show();

  context.subscriptions.push(
    openDashboardCommand,
    showDiagnosticsCommand,
    insertBoilerplateCommand,
    createProjectWizardCommand,
    statusBar
  );
}

export function deactivate(): void {
  // No-op
}

function severityToText(severity: vscode.DiagnosticSeverity): string {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error:
      return "Error";
    case vscode.DiagnosticSeverity.Warning:
      return "Warning";
    case vscode.DiagnosticSeverity.Information:
      return "Info";
    case vscode.DiagnosticSeverity.Hint:
      return "Hint";
    default:
      return "Unknown";
  }
}

function getChatLikeHtml(webview: vscode.Webview, logoUri: string): string {
  const nonce = createNonce();
  const csp = [
    "default-src 'none'",
    `img-src ${webview.cspSource} https: data:`,
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src 'nonce-${nonce}'`
  ].join("; ");

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="Content-Security-Policy" content="${csp}" />
    <title>AI Agent Starter Chat</title>
    <style>
      :root { color-scheme: dark; }
      body {
        font-family: "Segoe UI", "Inter", sans-serif;
        background: #1a1b1e;
        color: #e2e2e5;
        margin: 0;
        padding: 10px;
        box-sizing: border-box;
      }
      .chatBox {
        height: calc(100vh - 20px);
        background: #1e1f22;
        border: 1px solid #2c2d31;
        border-radius: 14px;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 12px 4px 14px;
      }
      .header .title {
        color: #9a9ba1;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 1.5px;
      }
      .header .actions {
        display: flex;
        gap: 6px;
      }
      .headerBtn {
        background: #232427;
        color: #c9c9cc;
        border: 1px solid #38393e;
        border-radius: 9px;
        padding: 4px 10px;
        font-size: 11px;
        cursor: pointer;
      }
      .headerBtn:hover { background: #2f3034; }
      .sep {
        background: #2c2d31;
        height: 1px;
      }
      .messages {
        flex: 1;
        overflow-y: auto;
        padding: 8px 12px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .bubble {
        border-radius: 12px;
        border: 1px solid;
        padding: 10px 12px 12px;
      }
      .bubble.user { background:#20293a; border-color:#2e4a73; }
      .bubble.assistant { background:#1f2620; border-color:#33472f; }
      .bubble.error { background:#2e1f20; border-color:#5a2c2c; }
      .bubble.system { background:#22242a; border-color:#33353c; }
      .bubbleHeader {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;
      }
      .avatar {
        width: 22px;
        height: 22px;
        border-radius: 11px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
      }
      .user .avatar { background:#2e4a73; }
      .assistant .avatar { background:#33472f; }
      .error .avatar { background:#5a2c2c; }
      .system .avatar { background:#3a2f5c; }
      .roleLabel { font-weight:700; font-size:12px; letter-spacing:0.3px; }
      .user .roleLabel { color:#6fb3ff; }
      .assistant .roleLabel { color:#9bd39c; }
      .error .roleLabel { color:#f48771; }
      .system .roleLabel { color:#c9a6ff; }
      .tag {
        margin-left: auto;
        color:#e0af68;
        background:#3a2f13;
        border-radius:8px;
        padding:1px 8px;
        font-size:10px;
        font-weight:600;
      }
      .content {
        white-space: pre-wrap;
        line-height: 1.5;
        font-family: Consolas, Menlo, monospace;
        font-size: 13px;
      }
      .attachmentsRow {
        padding: 0 12px;
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        min-height: 24px;
        align-items: center;
      }
      .chip {
        background:#232427;
        color:#c9c9cc;
        border:1px solid #38393e;
        border-radius:10px;
        padding:3px 10px;
        font-size:11px;
      }
      .composerWrap {
        padding: 0 12px 10px;
      }
      .composer {
        background:#2b2d31;
        border:1px solid #38393e;
        border-radius:14px;
        padding:8px 10px;
      }
      textarea {
        width: 100%;
        height: 64px;
        resize: none;
        border: none;
        outline: none;
        background: transparent;
        color: #eee;
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 13px;
        box-sizing: border-box;
      }
      .controls {
        display:flex;
        align-items:center;
        gap:5px;
      }
      select {
        background:#232427;
        color:#c9c9cc;
        padding:3px 8px;
        border:1px solid #38393e;
        border-radius:9px;
        font-size:10.5px;
        font-weight:600;
        min-height:24px;
      }
      .btn {
        background:#232427;
        color:#c9c9cc;
        padding:4px 8px;
        border:1px solid #38393e;
        border-radius:9px;
        font-size:11px;
        cursor:pointer;
      }
      .btn:hover { background:#2f3034; border-color:#47484d; }
      .btn.stop:hover { background:#3a2c2c; color:#f48771; border-color:#5a3535; }
      .btn.send {
        background:#6c8cff;
        color:white;
        border:none;
        padding:4px 12px;
        font-weight:700;
        min-width:22px;
      }
      .btn.send:hover { background:#7d9aff; }
      .btn[disabled] {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .spacer { flex: 1; }
      .logo {
        width: 18px;
        height: 18px;
        margin-right: 6px;
        vertical-align: middle;
      }
    </style>
  </head>
  <body>
    <div class="chatBox">
      <div class="header">
        <div class="title"><img class="logo" src="${logoUri}" alt="logo" />CHAT</div>
        <div class="actions">
          <button id="diagBtn" class="headerBtn" title="Show active file diagnostics">Diagnostics</button>
          <button id="wizardBtn" class="headerBtn" title="Open project wizard">Wizard</button>
        </div>
      </div>
      <div class="sep"></div>

      <div id="messages" class="messages"></div>

      <div id="attachmentsRow" class="attachmentsRow"></div>

      <div class="composerWrap">
        <div class="composer">
          <textarea id="input" placeholder="Ask the model to write/explain/fix code...  (Enter to send, Shift+Enter new line)"></textarea>
          <div class="controls">
            <select id="mode">
              <option>Agent</option>
              <option>Chat</option>
              <option>Plan</option>
            </select>
            <select id="backend">
              <option>gguf</option>
              <option>openrouter</option>
              <option>nvidia</option>
            </select>
            <button id="attachBtn" class="btn" title="Attach file">📎</button>
            <button id="clearBtn" class="btn" title="Clear conversation">🗑</button>
            <div class="spacer"></div>
            <button id="stopBtn" class="btn stop" disabled>Stop</button>
            <button id="sendBtn" class="btn send">➤</button>
          </div>
        </div>
      </div>
    </div>

    <script nonce="${nonce}">
      const vscode = acquireVsCodeApi();
      const messagesEl = document.getElementById("messages");
      const inputEl = document.getElementById("input");
      const modeEl = document.getElementById("mode");
      const backendEl = document.getElementById("backend");
      const attachmentsRowEl = document.getElementById("attachmentsRow");
      const attachBtnEl = document.getElementById("attachBtn");
      const clearBtnEl = document.getElementById("clearBtn");
      const stopBtnEl = document.getElementById("stopBtn");
      const sendBtnEl = document.getElementById("sendBtn");
      const diagBtnEl = document.getElementById("diagBtn");
      const wizardBtnEl = document.getElementById("wizardBtn");

      const attachments = [];
      let pendingAssistantContentEl = null;
      let isSending = false;

      function escapeHtml(text) {
        return text
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
      }

      function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      function setBusy(busy) {
        isSending = busy;
        sendBtnEl.disabled = busy;
        stopBtnEl.disabled = !busy;
      }

      function renderAttachments() {
        attachmentsRowEl.innerHTML = "";
        for (const fileName of attachments) {
          const chip = document.createElement("span");
          chip.className = "chip";
          chip.textContent = "📄 " + fileName;
          attachmentsRowEl.appendChild(chip);
        }
      }

      function addBubble(role, text, tag) {
        const bubble = document.createElement("div");
        bubble.className = "bubble " + role;

        const header = document.createElement("div");
        header.className = "bubbleHeader";

        const avatar = document.createElement("span");
        avatar.className = "avatar";
        avatar.textContent = role === "user" ? "🧑" : role === "assistant" ? "✨" : role === "error" ? "⚠" : "🛠";

        const roleLabel = document.createElement("span");
        roleLabel.className = "roleLabel";
        roleLabel.textContent = role === "user" ? "You" : role === "assistant" ? "Assistant" : role === "error" ? "Error" : "Agent";

        header.appendChild(avatar);
        header.appendChild(roleLabel);

        if (tag) {
          const tagEl = document.createElement("span");
          tagEl.className = "tag";
          tagEl.textContent = tag;
          header.appendChild(tagEl);
        }

        const content = document.createElement("div");
        content.className = "content";
        content.innerHTML = escapeHtml(text);

        bubble.appendChild(header);
        bubble.appendChild(content);
        messagesEl.appendChild(bubble);
        scrollToBottom();
        return content;
      }

      function updatePlaceholder() {
        const mode = modeEl.value;
        if (mode === "Plan") {
          inputEl.placeholder = "Describe what you want built - I will draft a plan first...  (Enter to send, Shift+Enter new line)";
          return;
        }
        if (mode === "Agent") {
          inputEl.placeholder = "Describe what to build or fix - the agent will edit/create files directly...  (Enter to send, Shift+Enter new line)";
          return;
        }
        inputEl.placeholder = "Ask the model to write/explain/fix code...  (Enter to send, Shift+Enter new line)";
      }

      function sendMessage() {
        if (isSending) {
          return;
        }
        const text = inputEl.value.trim();
        if (!text && attachments.length === 0) {
          return;
        }

        const mode = modeEl.value;
        const tag = mode === "Plan" ? "PLAN" : mode === "Agent" ? "AGENT" : "";
        const fullText = attachments.length > 0 ? "[" + attachments.join(", ") + "]\\n" + text : text;
        addBubble("user", fullText || "(attachment)", tag);

        pendingAssistantContentEl = addBubble("assistant", "Thinking...", "");

        vscode.postMessage({
          type: "sendMessage",
          text,
          mode,
          backend: backendEl.value,
          attachments: [...attachments]
        });

        inputEl.value = "";
        attachments.length = 0;
        renderAttachments();
        setBusy(true);
      }

      inputEl.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          sendMessage();
        }
      });

      modeEl.addEventListener("change", updatePlaceholder);

      attachBtnEl.addEventListener("click", () => {
        vscode.postMessage({ type: "attachRequested" });
      });

      clearBtnEl.addEventListener("click", () => {
        messagesEl.innerHTML = "";
        attachments.length = 0;
        renderAttachments();
        pendingAssistantContentEl = null;
      });

      stopBtnEl.addEventListener("click", () => {
        setBusy(false);
        if (pendingAssistantContentEl) {
          pendingAssistantContentEl.innerHTML = escapeHtml("Stopped.");
          pendingAssistantContentEl = null;
        }
      });

      sendBtnEl.addEventListener("click", sendMessage);
      diagBtnEl.addEventListener("click", () => vscode.postMessage({ type: "runDiagnostics" }));
      wizardBtnEl.addEventListener("click", () => vscode.postMessage({ type: "openWizard" }));

      window.addEventListener("message", (event) => {
        const message = event.data;

        if (message.type === "assistantReply") {
          if (!pendingAssistantContentEl) {
            pendingAssistantContentEl = addBubble("assistant", "", "");
          }
          pendingAssistantContentEl.innerHTML = escapeHtml(message.text || "");
          pendingAssistantContentEl = null;
          setBusy(false);
          return;
        }

        if (message.type === "attachmentAdded" && message.fileName) {
          attachments.push(message.fileName);
          renderAttachments();
        }
      });

      updatePlaceholder();
      addBubble("system", "Chat UI is now aligned with the PySide chat panel layout.", "READY");
    </script>
  </body>
</html>`;
}

async function runPythonChatBridge(
  extensionUri: vscode.Uri,
  req: BridgeRequest
): Promise<BridgeResult> {
  const bridgePath = path.join(extensionUri.fsPath, "bridge", "chat_bridge.py");
  const prompt = req.attachments.length > 0
    ? `[attachments: ${req.attachments.join(", ")}]\n${req.text}`
    : req.text;

  const payload = JSON.stringify({
    prompt,
    backend: req.backend,
    mode: req.mode
  });

  const candidates: Array<{ exe: string; args: string[] }> = [
    ...(process.env.PYTHON ? [{ exe: process.env.PYTHON, args: [] }] : []),
    { exe: "python", args: [] },
    { exe: "py", args: ["-3"] }
  ];

  let lastErr = "python executable not found";
  for (const candidate of candidates) {
    try {
      const { stdout } = await execFileAsync(candidate.exe, [
        ...candidate.args,
        bridgePath,
        payload
      ], path.dirname(path.dirname(extensionUri.fsPath)));
      const parsed = JSON.parse(stdout) as BridgeResult;
      return parsed;
    } catch (err) {
      lastErr = String(err);
    }
  }

  return {
    ok: false,
    error: `Bridge failed: ${lastErr}`
  };
}

function execFileAsync(
  exe: string,
  args: string[],
  cwd: string
): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    execFile(
      exe,
      args,
      { cwd, windowsHide: true, timeout: 120000 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr || error.message));
          return;
        }
        resolve({ stdout: String(stdout).trim(), stderr: String(stderr).trim() });
      }
    );
  });
}

function createNonce(length = 24): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let result = "";
  for (let i = 0; i < length; i += 1) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

type WebviewMessage = {
  type: "sendMessage";
  text: string;
  mode: string;
  backend: string;
  attachments: string[];
} | {
  type: "attachRequested";
} | {
  type: "runDiagnostics";
} | {
  type: "openWizard";
};

type BridgeRequest = {
  text: string;
  mode: string;
  backend: string;
  attachments: string[];
};

type BridgeResult = {
  ok: boolean;
  text?: string;
  error?: string;
};

async function writeTemplateFiles(
  projectRoot: vscode.Uri,
  files: Record<string, string>
): Promise<void> {
  for (const [relativePath, content] of Object.entries(files)) {
    const normalized = relativePath.replace(/\\/g, "/");
    const parts = normalized.split("/");
    const fileName = parts.pop();
    if (!fileName) {
      continue;
    }
    const dirPath = parts.join("/");
    const dirUri = dirPath ? vscode.Uri.joinPath(projectRoot, ...parts) : projectRoot;
    await vscode.workspace.fs.createDirectory(dirUri);
    const fileUri = dirPath
      ? vscode.Uri.joinPath(projectRoot, ...parts, fileName)
      : vscode.Uri.joinPath(projectRoot, fileName);
    await vscode.workspace.fs.writeFile(fileUri, new TextEncoder().encode(content));
  }
}

async function pathExists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

function buildReactTemplate(projectName: string): Record<string, string> {
  return {
    ".gitignore": "node_modules\ndist\n.vscode\n",
    "package.json": JSON.stringify(
      {
        name: projectName,
        private: true,
        version: "0.1.0",
        type: "module",
        scripts: {
          dev: "vite",
          build: "tsc -b && vite build",
          preview: "vite preview"
        },
        dependencies: {
          react: "^18.3.1",
          "react-dom": "^18.3.1"
        },
        devDependencies: {
          "@types/react": "^18.3.8",
          "@types/react-dom": "^18.3.0",
          "@vitejs/plugin-react": "^4.3.1",
          typescript: "^5.6.2",
          vite: "^5.4.8"
        }
      },
      null,
      2
    ) + "\n",
    "tsconfig.json": JSON.stringify(
      {
        compilerOptions: {
          target: "ES2020",
          useDefineForClassFields: true,
          lib: ["ES2020", "DOM", "DOM.Iterable"],
          module: "ESNext",
          skipLibCheck: true,
          moduleResolution: "Bundler",
          allowImportingTsExtensions: true,
          resolveJsonModule: true,
          isolatedModules: true,
          noEmit: true,
          jsx: "react-jsx",
          strict: true
        },
        include: ["src"]
      },
      null,
      2
    ) + "\n",
    "vite.config.ts": [
      "import { defineConfig } from \"vite\";",
      "import react from \"@vitejs/plugin-react\";",
      "",
      "export default defineConfig({",
      "  plugins: [react()]",
      "});",
      ""
    ].join("\n"),
    "index.html": [
      "<!doctype html>",
      "<html lang=\"en\">",
      "  <head>",
      "    <meta charset=\"UTF-8\" />",
      "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />",
      `    <title>${projectName}</title>`,
      "  </head>",
      "  <body>",
      "    <div id=\"root\"></div>",
      "    <script type=\"module\" src=\"/src/main.tsx\"></script>",
      "  </body>",
      "</html>",
      ""
    ].join("\n"),
    "src/main.tsx": [
      "import React from \"react\";",
      "import ReactDOM from \"react-dom/client\";",
      "import { App } from \"./App\";",
      "import \"./styles.css\";",
      "",
      "ReactDOM.createRoot(document.getElementById(\"root\")!).render(",
      "  <React.StrictMode>",
      "    <App />",
      "  </React.StrictMode>",
      ");",
      ""
    ].join("\n"),
    "src/App.tsx": [
      "export function App() {",
      "  return (",
      "    <main className=\"app\">",
      "      <h1>React Starter Ready</h1>",
      "      <p>Edit src/App.tsx to begin.</p>",
      "    </main>",
      "  );",
      "}",
      ""
    ].join("\n"),
    "src/styles.css": [
      ":root {",
      "  font-family: Segoe UI, Arial, sans-serif;",
      "  color: #111827;",
      "  background: #f8fafc;",
      "}",
      "",
      "body {",
      "  margin: 0;",
      "}",
      "",
      ".app {",
      "  padding: 2rem;",
      "}",
      ""
    ].join("\n"),
    "README.md": [
      `# ${projectName}`,
      "",
      "## Getting Started",
      "",
      "1. npm install",
      "2. npm run dev",
      ""
    ].join("\n")
  };
}

function buildNodeTemplate(projectName: string): Record<string, string> {
  return {
    ".gitignore": "node_modules\ndist\n.env\n",
    "package.json": JSON.stringify(
      {
        name: projectName,
        version: "0.1.0",
        private: true,
        main: "dist/index.js",
        scripts: {
          build: "tsc -p .",
          start: "node dist/index.js",
          dev: "ts-node src/index.ts"
        },
        devDependencies: {
          "@types/node": "^20.16.5",
          "ts-node": "^10.9.2",
          typescript: "^5.6.2"
        }
      },
      null,
      2
    ) + "\n",
    "tsconfig.json": JSON.stringify(
      {
        compilerOptions: {
          target: "ES2022",
          module: "commonjs",
          outDir: "dist",
          rootDir: "src",
          strict: true,
          esModuleInterop: true,
          skipLibCheck: true
        },
        include: ["src"]
      },
      null,
      2
    ) + "\n",
    "src/index.ts": [
      "function main(): void {",
      "  console.log(\"Node TypeScript starter is ready.\");",
      "}",
      "",
      "main();",
      ""
    ].join("\n"),
    "README.md": [
      `# ${projectName}`,
      "",
      "## Getting Started",
      "",
      "1. npm install",
      "2. npm run dev",
      "3. npm run build",
      "4. npm start",
      ""
    ].join("\n")
  };
}

function buildPythonTemplate(projectName: string): Record<string, string> {
  return {
    ".gitignore": "__pycache__/\n.venv/\n.pytest_cache/\n",
    "requirements.txt": [
      "pytest==8.3.3",
      ""
    ].join("\n"),
    "src/main.py": [
      "def greet(name: str) -> str:",
      "    return f\"Hello, {name}!\"",
      "",
      "",
      "if __name__ == \"__main__\":",
      "    print(greet(\"World\"))",
      ""
    ].join("\n"),
    "tests/test_main.py": [
      "from src.main import greet",
      "",
      "",
      "def test_greet() -> None:",
      "    assert greet(\"AI\") == \"Hello, AI!\"",
      ""
    ].join("\n"),
    "README.md": [
      `# ${projectName}`,
      "",
      "## Getting Started",
      "",
      "1. python -m venv .venv",
      "2. .venv\\Scripts\\activate",
      "3. pip install -r requirements.txt",
      "4. python src/main.py",
      "5. pytest",
      ""
    ].join("\n")
  };
}