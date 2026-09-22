import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <TooltipPrimitive.Provider delayDuration={150}>{children}</TooltipPrimitive.Provider>;
}

export function Tooltip({
  trigger,
  content,
  label,
}: {
  trigger: ReactNode;
  content: ReactNode;
  label: string;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild aria-label={label}>
        {trigger}
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Content
        side="top"
        align="center"
        sideOffset={6}
        className="z-50 max-w-xs rounded-md bg-ink px-3 py-2 text-xs leading-relaxed text-white"
      >
        {content}
        <TooltipPrimitive.Arrow className="fill-ink" />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Root>
  );
}
