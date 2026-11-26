import clsx from "clsx";

const VARIANTS = {
  primary: "bg-primary text-primary-fg hover:bg-primary-hover",
  outline: "border border-line-strong bg-surface text-fg hover:bg-surface-2",
  ghost: "text-fg-muted hover:bg-surface-2 hover:text-fg",
} as const;

type ButtonProps = React.ComponentProps<"button"> & { variant?: keyof typeof VARIANTS };

export function Button({ variant = "outline", className, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      className={clsx(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-xl px-3.5 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

export function IconButton({
  label,
  className,
  ...props
}: React.ComponentProps<"button"> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={clsx(
        "inline-flex size-10 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg",
        className,
      )}
      {...props}
    />
  );
}
