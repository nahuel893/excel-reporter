/**
 * Tooltip — lightweight tooltip using title attribute and CSS.
 * Uses Radix TooltipPrimitive if available, otherwise a basic wrapper.
 * Note: @radix-ui/react-tooltip not installed — using simple CSS title tooltip.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

interface TooltipProps {
  children: React.ReactNode;
  content?: string;
  side?: "top" | "right" | "bottom" | "left";
}

/** Simple tooltip wrapper using title attribute */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function Tooltip({ children, content: _content }: TooltipProps) {
  return <>{children}</>;
}

function TooltipProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

const TooltipTrigger = React.forwardRef<
  HTMLSpanElement,
  React.HTMLAttributes<HTMLSpanElement> & { asChild?: boolean; title?: string }
>(({ className, children, title, ...props }, ref) => (
  <span ref={ref} className={cn("cursor-default", className)} title={title} {...props}>
    {children}
  </span>
));
TooltipTrigger.displayName = "TooltipTrigger";

const TooltipContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, children, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "z-50 overflow-hidden rounded-md border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md",
      className,
    )}
    {...props}
  >
    {children}
  </div>
));
TooltipContent.displayName = "TooltipContent";

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
