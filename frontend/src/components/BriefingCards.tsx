import type { BriefingCard } from "@/api/types";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMoney } from "@/lib/user-api";

type CardFor<T extends BriefingCard["card_type"]> = BriefingCard & { card_type: T };

function CardShell({ title, children }: { title: string; children: React.ReactNode }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-2">{children}</CardContent></Card>;
}

function YesterdayCard({ card, backfillHref }: { card?: CardFor<"yesterday">; backfillHref: string }) {
  if (!card || card.state === "unavailable") return <CardShell title="昨日"><p>昨日简报暂不可用</p></CardShell>;
  if (card.state === "missing") return <CardShell title="昨日"><p>昨日尚未记录</p><a className={buttonVariants({ variant: "outline", size: "sm" })} href={backfillHref}>补记昨日</a></CardShell>;
  const status = card.state === "rest" ? "昨日休息" : card.state === "weather_closed" ? "昨日天气停业" : "昨日已记录";
  return <CardShell title="昨日"><p>{status}</p>{card.revenue !== null && <p className="text-2xl font-semibold">{formatMoney(card.revenue)}</p>}</CardShell>;
}

function TodayCard({ card }: { card?: CardFor<"today"> }) {
  if (!card || card.state === "unavailable") return <CardShell title="今日"><p>今日简报暂不可用</p></CardShell>;
  const status = card.state === "missing" ? "今日尚未记账" : card.state === "rest" ? "今日休息" : card.state === "weather_closed" ? "今日天气停业" : "今日已记录";
  return <CardShell title="今日"><p>{status}</p>{card.revenue !== null && <p className="text-2xl font-semibold">{formatMoney(card.revenue)}</p>}{card.weather && <p>{card.weather}</p>}</CardShell>;
}

function TomorrowCard({ card }: { card?: CardFor<"tomorrow"> }) {
  if (!card || card.state === "unavailable") return <CardShell title="明日"><p>明日预报暂不可用</p></CardShell>;
  return <CardShell title="明日">
    {card.weekday && <p>{card.weekday}</p>}
    {card.weather && <p>{card.weather}</p>}
    {card.temperature_min !== null && card.temperature_max !== null && <p>{card.temperature_min}°C – {card.temperature_max}°C</p>}
    {card.precipitation !== null && <p>预计降水 {card.precipitation} mm</p>}
    {card.hint && <p className="text-sm text-muted-foreground">{card.hint}</p>}
  </CardShell>;
}

export function BriefingCards({ cards, yesterdayHref }: { cards: BriefingCard[]; yesterdayHref: string }) {
  const yesterday = cards.find((card): card is CardFor<"yesterday"> => card.card_type === "yesterday");
  const today = cards.find((card): card is CardFor<"today"> => card.card_type === "today");
  const tomorrow = cards.find((card): card is CardFor<"tomorrow"> => card.card_type === "tomorrow");
  return <div className="grid gap-4 md:grid-cols-3">
    <YesterdayCard card={yesterday} backfillHref={yesterdayHref} />
    <TodayCard card={today} />
    <TomorrowCard card={tomorrow} />
  </div>;
}
