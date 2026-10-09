import { Button } from "@/components/ui/button";

export const chatQuestions = [
  { title: "本月经营概览", prompt: "请概括当前门店本月至今的经营情况，说明收入、经营日和数据覆盖，区分未统计、未录入与真实零收入。先给结论，再列证据；无法查询的指标请明确说明。" },
  { title: "每日收入折线图", prompt: "我想看当前门店上个月每天的台账营业额折线图，不含公司结算。请覆盖整月，保留休息日的零值和未统计、未录入日期的空值，简短说明趋势和数据覆盖。" },
  { title: "与上月同期比较", prompt: "请比较当前门店本月至今与上月相同进度的经营表现，明确两段实际日期、收入与经营日，并说明数据覆盖差异。没有可比数据时请说明原因，不推断增长原因。" },
  { title: "收入构成", prompt: "请查询当前门店上个月的收入构成，列出各个计入总收入的收入分类和已确认公司结算的金额，生成分类柱状图。未启用或无法查询的项目请明确说明；不计入总收入的项目单独说明，不将总额与分项重复相加。" },
  { title: "计算小示例", prompt: "请用计算工具计算 (1250 + 850) × 0.15，给出计算结果。这只是算式示例，不是门店的实际经营数据。" },
  { title: "记住回答偏好", prompt: "记住我的回答偏好：以后先给结论，再列关键数据，尽量控制在三条以内。请说明这条偏好的保存状态。" },
];

const examples = [
  { title: "经营概览及追问", turns: [
    ["你", "查看本月经营情况时，我应该先关注什么？"],
    ["AI 助手", "先核对查询日期和数据覆盖，再看每日台账营业额、经营日及已确认公司结算。未统计和未录入不当作零收入；经营日均台账营业额不包含公司结算。"],
    ["你", "收入比上月高，就代表经营变好了吗？"],
    ["AI 助手", "还要比较相同进度的日期、经营日和数据覆盖。集中清点、公司结算或记录不完整都可能影响金额；没有事件或其他证据，不能直接认定增长原因。点击“与上月同期比较”可发起当前门店的实际查询。"],
  ] },
  { title: "收入构成与结算解释", turns: [
    ["你", "每日台账与公司结算有什么区别？"],
    ["AI 助手", "每日台账按日记录营业额；公司结算按开票月份归属，只有确认到账后才计入该月总收入。待到账应收款表示当前应收状态，不属于已确认收入。"],
    ["你", "确认到账后，可以把金额平均分到每天吗？"],
    ["AI 助手", "不能。公司结算没有日粒度，不改变任何一天的台账营业额。部分月份查询与开票月份有重叠时，会纳入该月整笔已确认结算，因此不同日期片段的结果不能直接相加，以免重复计入。"],
  ] },
  { title: "未统计与集中清点解释", turns: [
    ["你", "未统计是不是零营业额？"],
    ["AI 助手", "不是。未统计表示已有台账，但金额和洗车数量尚未知；未录入表示当天没有台账。休息表示全天不营业且经营数值为零，营业状态下明确录入的零才是已知零收入。未统计与未录入不增加经营日或相关均值的分母。"],
    ["你", "几天的收入一起清点，之前的日期怎么办？"],
    ["AI 助手", "金额记在清点当天，之前的日期保持未统计，可在事件中说明覆盖时段。系统不自动平摊；分析时也不能仅凭附近有未统计日期，就认定收入覆盖了这些日期。"],
  ] },
];

export function ChatQuestionButtons({ onSelect, disabled }: { onSelect: (prompt: string) => void; disabled: boolean }) {
  return <section aria-label="固定提问" className="mb-3 grid gap-2">
    <p className="text-xs text-muted-foreground">体验经营查询、图表、比较、计算和记忆 · 选择后可编辑再发送</p>
    <div className="flex min-w-0 gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:flex-wrap">
      {chatQuestions.map((question) => <Button key={question.title} type="button" size="sm" variant="outline" disabled={disabled}
        className="h-8 shrink-0 rounded-full px-3 text-xs" onClick={() => onSelect(question.prompt)}>{question.title}</Button>)}
    </div>
  </section>;
}

export function ChatExamplePreview({ onOpen }: { onOpen: (index: number) => void }) {
  return <section aria-label="示例提问思路" className="rounded-2xl border bg-card p-4">
    <h2 className="text-sm font-semibold">先看看怎么问</h2>
    <p className="mt-1 text-xs leading-5 text-muted-foreground">从经营概览到追问，看看如何得到更清楚的回答。</p>
    <div className="mt-3 grid gap-2">
      {examples.map((example, index) => <button key={example.title} type="button" onClick={() => onOpen(index)}
        className="group rounded-xl border bg-background p-3 text-left transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <span className="block text-xs font-medium text-primary">示例 0{index + 1}</span>
        <span className="mt-1 block text-sm font-medium">{example.title}</span>
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">{example.turns[0][1]}</span>
      </button>)}
    </div>
    <p className="mt-3 text-[11px] leading-5 text-muted-foreground">预设演示问答 · 与你的真实历史分开展示</p>
  </section>;
}

export function ChatExamples({ initialExample = 0 }: { initialExample?: number }) {
  return <details open className="rounded-2xl border bg-card p-3 sm:p-4">
    <summary className="cursor-pointer text-sm font-semibold">示例会话 · 3 个提问思路</summary>
    <div role="region" aria-label="示例会话" className="mt-3 grid gap-2">
      <p className="text-xs leading-5 text-muted-foreground">以下为预设演示问答，不是实际查询记录，不包含实时经营金额。当前门店的数据请通过下方聊天查询；重置对话不会清除这些示例。</p>
      {examples.map((example, index) => <details key={example.title} open={index === initialExample} className="rounded-lg border px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium">{example.title}</summary>
        <div className="mt-3 grid gap-3">
          {example.turns.map(([role, content], turnIndex) => <div key={turnIndex} className={`rounded-lg p-3 text-sm leading-6 ${role === "你" ? "bg-primary/10" : "bg-muted/50"}`}>
            <p className="mb-1 text-xs font-medium text-muted-foreground">{role} · 示例</p>
            <p className="break-words">{content}</p>
          </div>)}
        </div>
      </details>)}
    </div>
  </details>;
}
