export function NonMedicalNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? 'space-y-2 text-xs leading-5 text-zinc-500' : 'space-y-3 text-sm leading-6 text-zinc-600'}>
      <p>
        本服务不是医疗诊断工具，不能替代专业心理咨询、精神科医生或紧急援助。
      </p>
      <p>
        如果你正在经历自伤、自杀、伤害他人或其他紧急危险，请立即拨打 110 或 120，并联系身边可信任的人。
      </p>
      <p>
        人工安全值守时间为工作日 09:00–18:00（中国时间），本服务不是 7×24 小时危机热线。
      </p>
    </div>
  )
}

export function PrivacyNotice() {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm leading-6 text-zinc-600">
      <h2 className="text-sm font-semibold text-zinc-900">隐私提示</h2>
      <p className="mt-2">
        咨询式对话会用于生成本账号的上下文、记忆、总结和计划。请避免输入身份证号、银行卡号、住址等高度敏感信息。
      </p>
      <p className="mt-2">
        这里是 AI 辅助对话，不是真人咨询师。你可以在账号设置中自助导出数据、申请删除或提交投诉。
      </p>
    </div>
  )
}

export function CrisisNotice() {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
      <h2 className="text-sm font-semibold">紧急情况</h2>
      <p className="mt-2">
        如果危险正在发生，请立即拨打 110 或 120，远离危险物品和地点，不要独处，并联系一位可信任的人陪伴。
      </p>
      <p className="mt-2 font-medium">
        人工安全值守时间为工作日 09:00–18:00（中国时间）；其他时段无人实时查看。
      </p>
    </div>
  )
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 p-6 text-center">
      <p className="text-sm font-medium text-zinc-900">{title}</p>
      <p className="mt-2 text-sm leading-6 text-zinc-600">{body}</p>
    </div>
  )
}
