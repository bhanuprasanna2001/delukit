import { ChevronDown } from "lucide-react";
import type { SelectHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select
        className={cn(
          "h-9 w-full cursor-pointer appearance-none rounded-md border border-line bg-card pl-3 pr-9 text-sm text-ink transition-colors hover:border-ink-faint focus:border-brand focus:outline-none",
          className,
        )}
        {...props}
      />
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-faint" />
    </div>
  );
}
