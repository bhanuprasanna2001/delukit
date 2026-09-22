import type { InputHTMLAttributes, Ref } from "react";
import { cn } from "../../lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  ref?: Ref<HTMLInputElement>;
}

export function Input({ className, ref, ...props }: InputProps) {
  return (
    <input
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md border border-line bg-card px-3 py-1 text-sm",
        "placeholder:text-ink-faint focus:border-brand",
        className,
      )}
      {...props}
    />
  );
}
