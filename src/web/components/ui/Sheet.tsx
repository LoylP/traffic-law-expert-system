"use client";

import clsx from "clsx";
import { useEffect, useRef } from "react";

type SheetProps = {
  open: boolean;
  onClose: () => void;
  side: "left" | "bottom" | "center";
  label: string;
  children: React.ReactNode;
};

/** Modal built on <dialog>, which provides the focus trap and Esc to close. */
export function Sheet({ open, onClose, side, label, children }: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      onClose={onClose}
      // A click on the dialog element itself is a click on the backdrop.
      onClick={(event) => event.target === ref.current && onClose()}
      className={clsx("sheet", `sheet-${side}`)}
    >
      {open && children}
    </dialog>
  );
}
