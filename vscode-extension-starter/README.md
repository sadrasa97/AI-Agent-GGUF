# AI Agent Starter Extension

This folder contains a complete, separate VS Code extension scaffold.

## Features

- Dashboard webview command with logo
- Chat webview UI modeled after the PySide chat section
- Diagnostics viewer for active file
- TypeScript boilerplate snippet insertion command
- Project creation wizard (React/Node/Python templates)
- Status bar shortcut

## Commands

- `AI Agent Starter: Open Dashboard`
- `AI Agent Starter: Show Active File Diagnostics`
- `AI Agent Starter: Insert TypeScript Boilerplate`
- `AI Agent Starter: Create Project (React/Node/Python)`

## Project Structure

```text
vscode-extension-starter/
  src/
    extension.ts
  media/
    logo.svg
  .vscode/
    launch.json
    tasks.json
  package.json
  tsconfig.json
  .vscodeignore
  .gitignore
  CHANGELOG.md
  README.md
```

## Run in Development

1. Open this folder in VS Code:
   - `File > Open Folder...` -> select `vscode-extension-starter`
2. Install dependencies:
   - `npm install`
3. Compile:
   - `npm run compile`
4. Press `F5` to launch the Extension Development Host.
5. Open Command Palette and run one of the extension commands.

## Package VSIX (Optional)

1. Install packaging tool:
   - `npm i -g @vscode/vsce`
2. Build extension package:
   - `vsce package`
