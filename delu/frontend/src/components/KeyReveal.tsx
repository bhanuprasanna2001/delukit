import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "./ui/button";

export function KeyReveal({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="grid gap-2 rounded-md border border-line bg-paper p-3">
      <code className="break-all font-mono text-sm tnum">{value}</code>
      <div>
        <Button type="button" variant="outline" size="sm" onClick={copy}>
          {copied ? <Check /> : <Copy />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}
