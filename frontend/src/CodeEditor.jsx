import React from "react";
import Editor, { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import "monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution";
import "monaco-editor/esm/vs/basic-languages/cpp/cpp";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

export default function CodeEditor({ value, onChange, readOnly = false, language = "cpp", height = "100%", markers = [] }) {
  return (
    <Editor
      height={height} language={language === "ll" ? "plaintext" : "cpp"} theme="vs" value={value}
      onChange={(v) => onChange && onChange(v ?? "")}
      onMount={(ed, m) => {
        const model = ed.getModel();
        m.editor.setModelMarkers(model, "clang", markers.map((d) => ({
          startLineNumber: d.line, startColumn: d.col, endLineNumber: d.line, endColumn: d.col + 1,
          message: d.message, severity: d.severity === "error" ? 8 : 4,
        })));
      }}
      options={{ readOnly, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, automaticLayout: true,
        fontFamily: "'IBM Plex Mono',Consolas,monospace", renderLineHighlight: "line", tabSize: 4,
        smoothScrolling: false, cursorBlinking: "solid", cursorSmoothCaretAnimation: "off", padding: { top: 8, bottom: 8 } }}
    />
  );
}
