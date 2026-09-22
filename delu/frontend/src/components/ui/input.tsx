import type { InputHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-9 w-full rounded-md border border-line bg-card px-3 py-1 text-sm",
        "placeholder:text-ink-faint focus:border-brand",
        className,
      )}
      {...props}
    />
  );
}
