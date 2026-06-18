/**
 * Badge — shadcn-style badge with variant support + tipo-specific colors.
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/20 text-primary",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-destructive/20 text-destructive",
        outline:
          "text-foreground border-border",
        /* Tipo-specific variants */
        ventas: "border-transparent bg-blue-500/15 text-blue-400",
        avances: "border-transparent bg-violet-500/15 text-violet-400",
        "champions-league": "border-transparent bg-amber-500/15 text-amber-400",
        "resumen-mensual": "border-transparent bg-emerald-500/15 text-emerald-400",
        "stock-diario": "border-transparent bg-cyan-500/15 text-cyan-400",
        "historico-fratelli": "border-transparent bg-amber-600/15 text-amber-500",
        cartesiano: "border-transparent bg-orange-500/15 text-orange-400",
        "graficos-cobertura": "border-transparent bg-pink-500/15 text-pink-400",
        "ventas-articulo": "border-transparent bg-sky-500/15 text-sky-400",
        "historico-cliente": "border-transparent bg-indigo-500/15 text-indigo-400",
        "reporte-general-badie": "border-transparent bg-emerald-600/15 text-emerald-500",
        "reporte-rebotes": "border-transparent bg-rose-500/15 text-rose-400",
        /* Fallback */
        zinc: "border-transparent bg-zinc-700/50 text-zinc-400",
        success: "border-transparent bg-emerald-500/15 text-emerald-400",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
