import type { BriefingCard } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
const titles = { yesterday: "昨天", today: "今天", tomorrow: "明天" } as const;
export function BriefingCards({ cards }: { cards: BriefingCard[] }) {
  const byType = new Map(cards.map((card) => [card.card_type, card]));
  return <div className="grid gap-4 md:grid-cols-3">{(["yesterday", "today", "tomorrow"] as const).map((type) => <Card key={type}><CardHeader><CardTitle>{titles[type]}</CardTitle></CardHeader><CardContent>{byType.get(type)?.content ?? "暂无简报"}</CardContent></Card>)}</div>;
}
