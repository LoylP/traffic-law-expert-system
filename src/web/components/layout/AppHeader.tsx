import { Menu } from "lucide-react";

import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Badge } from "@/components/ui/Badge";
import { IconButton } from "@/components/ui/Button";

type AppHeaderProps = {
  title: string;
  badge: string;
  onOpenMenu: () => void;
};

export function AppHeader({ title, badge, onOpenMenu }: AppHeaderProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-2 sm:px-4">
      <IconButton label="Mở menu" onClick={onOpenMenu} className="lg:hidden">
        <Menu size={18} aria-hidden />
      </IconButton>
      <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold">{title}</h1>
      <Badge tone="accent" className="shrink-0 whitespace-nowrap">
        {badge}
      </Badge>
      <ThemeToggle />
    </header>
  );
}
