import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Clock } from "lucide-react";

// "Bota iletildi" rozeti — beklemede olan panel işlemleri için.
export function QueuedBadge({ className, label = "Bota iletildi" }) {
  return (
    <Badge
      data-testid="queued-badge"
      className={cn(
        "gap-1 border border-info/40 bg-info/10 text-info hover:bg-info/10 font-medium",
        className
      )}
    >
      <Clock className="h-3 w-3 animate-blink" />
      {label}
    </Badge>
  );
}
