import { useState } from "react";

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.left = "-9999px";
  document.body.appendChild(field);
  field.select();
  document.execCommand("copy");
  document.body.removeChild(field);
}

export default function CopyButton({ text, label = "Copy link" }) {
  const [copied, setCopied] = useState(false);

  async function onClick() {
    try {
      await writeClipboard(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      setCopied(false);
    }
  }

  return (
    <button type="button" className="btn btn-ghost" onClick={onClick}>
      {copied ? "Copied" : label}
    </button>
  );
}
