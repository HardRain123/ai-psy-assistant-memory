'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'

type ScreeningOption = {
  value: number
  label: string
}

type InstrumentConfig = {
  code: string
  title: string
  subtitle: string
  score_type: 'sum' | 'average' | string
  min_value: number
  max_value: number
  options: ScreeningOption[]
  questions: string[]
}

type SupplementalQuestion = {
  code: string
  prompt: string
  options: ScreeningOption[]
}

type SupplementalModuleConfig = {
  code: string
  title: string
  subtitle: string
  trigger: {
    type: string
    score?: number
  }
  questions: SupplementalQuestion[]
}

type ScreeningResult = {
  instrument: string
  title: string
  score: number
  severity: string
  label: string
  recommendation: string
  risk_level: string
  risk_flags: string[]
  is_diagnosis: boolean
  disclaimer: string
  screening_id?: number
  created_at?: string
}

type Snapshot = {
  summary?: string
  updated_at?: string
  stage?: 'stable' | 'mild' | 'moderate' | 'high_attention' | 'urgent_attention' | string
  confidence?: 'low' | 'medium' | 'high' | string
  trend?: 'improving' | 'stable' | 'worsening' | 'unknown' | string
  safety?: {
    risk_level?: string
    flags?: string[]
  }
  screenings?: Record<
    string,
    {
      score: number
      label: string
      severity: string
      created_at?: string
      is_diagnosis?: boolean
    }
  >
}

type BootstrapData = {
  config?: {
    instruments?: InstrumentConfig[]
    supplemental_modules?: SupplementalModuleConfig[]
  }
  current?: {
    exists?: boolean
    snapshot?: Snapshot | null
  }
}

const INSTRUMENT_ORDER = ['phq9', 'gad7', 'asrm', 'des2']
const SUPPLEMENT_ORDER = ['stage', 'safety', 'mania', 'anxiety', 'dissociation']

function formatDate(value?: string) {
  if (!value) return '暂无记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function severityTone(severity?: string) {
  if (severity === 'severe' || severity === 'moderately_severe' || severity === 'high') {
    return 'border-red-200 bg-red-50 text-red-800'
  }
  if (severity === 'moderate' || severity === 'elevated') {
    return 'border-amber-200 bg-amber-50 text-amber-900'
  }
  if (severity === 'mild') {
    return 'border-sky-200 bg-sky-50 text-sky-800'
  }
  return 'border-emerald-200 bg-emerald-50 text-emerald-800'
}

function stageTone(stage?: string) {
  if (stage === 'urgent_attention') return 'border-red-200 bg-red-50 text-red-800'
  if (stage === 'high_attention') return 'border-orange-200 bg-orange-50 text-orange-900'
  if (stage === 'moderate') return 'border-amber-200 bg-amber-50 text-amber-900'
  if (stage === 'mild') return 'border-sky-200 bg-sky-50 text-sky-800'
  return 'border-emerald-200 bg-emerald-50 text-emerald-800'
}

function riskCopy(level?: string) {
  if (level === 'high') return '高风险提示'
  if (level === 'medium') return '中等风险提示'
  if (level === 'low') return '轻度风险提示'
  return '未见明显安全风险'
}

function stageCopy(stage?: string) {
  if (stage === 'urgent_attention') return '紧急关注'
  if (stage === 'high_attention') return '高关注'
  if (stage === 'moderate') return '中度关注'
  if (stage === 'mild') return '轻度关注'
  return '稳定/未见明显风险'
}

function confidenceCopy(confidence?: string) {
  if (confidence === 'high') return '高'
  if (confidence === 'medium') return '中'
  return '低'
}

function trendCopy(trend?: string) {
  if (trend === 'improving') return '改善'
  if (trend === 'stable') return '稳定'
  if (trend === 'worsening') return '加重'
  return '暂无足够历史'
}

function numericAnswers(values?: Array<number | null>) {
  if (!values || values.some((value) => value === null)) return null
  return values.map((value) => Number(value))
}

function scoreInstrument(instrument: InstrumentConfig, values?: Array<number | null>) {
  const nums = numericAnswers(values)
  if (!nums) return null
  if (instrument.score_type === 'average') {
    return nums.reduce((sum, value) => sum + value, 0) / nums.length
  }
  return nums.reduce((sum, value) => sum + value, 0)
}

function normalizeBootstrap(data: BootstrapData | null | undefined) {
  const config = data?.config || {}
  const loaded = [...(config.instruments || [])].sort(
    (a: InstrumentConfig, b: InstrumentConfig) =>
      INSTRUMENT_ORDER.indexOf(a.code) - INSTRUMENT_ORDER.indexOf(b.code)
  )
  const modules = [...(config.supplemental_modules || [])].sort(
    (a: SupplementalModuleConfig, b: SupplementalModuleConfig) =>
      SUPPLEMENT_ORDER.indexOf(a.code) - SUPPLEMENT_ORDER.indexOf(b.code)
  )
  return {
    instruments: loaded,
    supplementalModules: modules,
    snapshot: data?.current?.exists ? data.current.snapshot || null : null,
  }
}

export function AssessmentClient({ initialData = null }: { initialData?: BootstrapData | null }) {
  const normalizedInitial = normalizeBootstrap(initialData)
  const router = useRouter()
  const [instruments, setInstruments] = useState<InstrumentConfig[]>(normalizedInitial.instruments)
  const [supplementalModules, setSupplementalModules] = useState<SupplementalModuleConfig[]>(
    normalizedInitial.supplementalModules
  )
  const [answers, setAnswers] = useState<Record<string, Array<number | null>>>(
    Object.fromEntries(
      normalizedInitial.instruments.map((instrument: InstrumentConfig) => [
        instrument.code,
        Array(instrument.questions.length).fill(null),
      ])
    )
  )
  const [supplementAnswers, setSupplementAnswers] = useState<Record<string, Array<number | null>>>(
    Object.fromEntries(
      normalizedInitial.supplementalModules.map((module: SupplementalModuleConfig) => [
        module.code,
        Array(module.questions.length).fill(null),
      ])
    )
  )
  const [activeCode, setActiveCode] = useState(normalizedInitial.instruments[0]?.code || 'phq9')
  const [results, setResults] = useState<Record<string, ScreeningResult>>({})
  const [snapshot, setSnapshot] = useState<Snapshot | null>(normalizedInitial.snapshot)
  const [loading, setLoading] = useState(!initialData)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (initialData) return
    let cancelled = false

    async function loadInitial() {
      try {
        const res = await fetch('/api/screening/bootstrap')

        if (res.status === 401) {
          router.replace('/login')
          return
        }

        const data = await res.json().catch(() => ({}))
        if (cancelled) return

        if (!res.ok) {
          setError(data.error || '无法读取状态评估配置。')
          return
        }

        const normalized = normalizeBootstrap(data)
        const loaded = normalized.instruments
        const modules = normalized.supplementalModules

        setInstruments(loaded)
        setSupplementalModules(modules)
        setActiveCode(loaded[0]?.code || 'phq9')
        setAnswers(
          Object.fromEntries(
            loaded.map((instrument: InstrumentConfig) => [
              instrument.code,
              Array(instrument.questions.length).fill(null),
            ])
          )
        )
        setSupplementAnswers(
          Object.fromEntries(
            modules.map((module: SupplementalModuleConfig) => [
              module.code,
              Array(module.questions.length).fill(null),
            ])
          )
        )

        setSnapshot(normalized.snapshot)
      } catch {
        if (!cancelled) {
          setError('网络连接不稳定，请稍后再试。')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadInitial()

    return () => {
      cancelled = true
    }
  }, [initialData, router])

  const coreScores = useMemo(() => {
    return Object.fromEntries(
      instruments.map((instrument) => [instrument.code, scoreInstrument(instrument, answers[instrument.code])])
    ) as Record<string, number | null>
  }, [answers, instruments])

  const coreCompletion = useMemo(() => {
    const total = instruments.reduce((sum, instrument) => sum + instrument.questions.length, 0)
    const answered = instruments.reduce((sum, instrument) => {
      return sum + (answers[instrument.code] || []).filter((value) => value !== null).length
    }, 0)
    return { answered, total }
  }, [answers, instruments])

  const coreComplete = coreCompletion.total > 0 && coreCompletion.answered === coreCompletion.total
  const phqSelfHarmPositive = (answers.phq9?.[8] ?? null) !== null && Number(answers.phq9?.[8] || 0) > 0

  const visibleSupplementalModules = useMemo(() => {
    return supplementalModules.filter((module) => {
      if (module.code === 'stage') return coreComplete
      if (module.code === 'safety') return phqSelfHarmPositive
      if (module.code === 'mania') return (coreScores.asrm ?? -1) >= 6
      if (module.code === 'anxiety') return (coreScores.gad7 ?? -1) >= 10
      if (module.code === 'dissociation') return (coreScores.des2 ?? -1) >= 30
      return false
    })
  }, [coreComplete, coreScores, phqSelfHarmPositive, supplementalModules])

  const visibleCodes = useMemo(
    () =>
      new Set([
        ...instruments.map((instrument) => instrument.code),
        ...visibleSupplementalModules.map((module) => module.code),
      ]),
    [instruments, visibleSupplementalModules]
  )
  const effectiveActiveCode = visibleCodes.has(activeCode)
    ? activeCode
    : instruments[0]?.code || visibleSupplementalModules[0]?.code || 'phq9'
  const activeInstrument = useMemo(
    () => instruments.find((instrument) => instrument.code === effectiveActiveCode) || null,
    [effectiveActiveCode, instruments]
  )
  const activeSupplementalModule = useMemo(
    () => visibleSupplementalModules.find((module) => module.code === effectiveActiveCode) || null,
    [effectiveActiveCode, visibleSupplementalModules]
  )

  const supplementalCompletion = useMemo(() => {
    const total = visibleSupplementalModules.reduce((sum, module) => sum + module.questions.length, 0)
    const answered = visibleSupplementalModules.reduce((sum, module) => {
      return sum + (supplementAnswers[module.code] || []).filter((value) => value !== null).length
    }, 0)
    return { answered, total }
  }, [supplementAnswers, visibleSupplementalModules])

  const supplementalComplete = supplementalCompletion.answered === supplementalCompletion.total
  const canSubmit = coreComplete && supplementalComplete
  const orderedResults = INSTRUMENT_ORDER.map((code) => results[code]).filter(Boolean)

  function setAnswer(instrumentCode: string, index: number, value: number) {
    setAnswers((prev) => {
      const next = [...(prev[instrumentCode] || [])]
      next[index] = value
      return { ...prev, [instrumentCode]: next }
    })
  }

  function setSupplementAnswer(moduleCode: string, index: number, value: number) {
    setSupplementAnswers((prev) => {
      const next = [...(prev[moduleCode] || [])]
      next[index] = value
      return { ...prev, [moduleCode]: next }
    })
  }

  async function submitAll() {
    if (!canSubmit || submitting) return
    setError('')
    setNotice('')
    setSubmitting(true)

    try {
      const screenings = instruments.map((instrument) => {
        const values = numericAnswers(answers[instrument.code])
        if (!values) {
          throw new Error('incomplete_answers')
        }
        return {
          instrument: instrument.code,
          answers: values,
        }
      })

      const supplements = Object.fromEntries(
        visibleSupplementalModules.map((module) => {
          const values = numericAnswers(supplementAnswers[module.code])
          if (!values) {
            throw new Error('incomplete_supplements')
          }
          return [module.code, values]
        })
      )

      const res = await fetch('/api/screening/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ screenings, supplements }),
      })
      const data = await res.json().catch(() => ({}))

      if (res.status === 401) {
        router.replace('/login')
        return
      }
      if (!res.ok) {
        throw new Error(data.error || 'submit_failed')
      }

      const resultMap =
        data.results_by_instrument ||
        Object.fromEntries((data.results || []).map((result: ScreeningResult) => [result.instrument, result]))
      setResults(resultMap)
      setSnapshot(data.snapshot || null)
      setNotice('状态评估已保存，并会以摘要、阶段和风险提示进入聊天上下文。')
      window.setTimeout(() => {
        document.getElementById('assessment-results')?.scrollIntoView({ behavior: 'smooth' })
      }, 0)
    } catch {
      setError('状态评估提交失败，请检查答案后稍后再试。')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <section className="mx-auto max-w-6xl px-4 py-5">
        <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-500">
          正在加载状态评估...
        </div>
      </section>
    )
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-4 px-4 py-5 lg:grid-cols-[280px_1fr]">
      <aside className="space-y-4">
        <section className="rounded-lg border border-zinc-200 bg-white p-4">
          <h1 className="text-base font-semibold text-zinc-900">状态评估</h1>
          <p className="mt-2 text-sm leading-6 text-zinc-600">
            结果仅为筛查提示，不是医疗诊断。
          </p>
          <div className="mt-4 text-sm text-zinc-600">
            核心量表 {coreCompletion.answered}/{coreCompletion.total}
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-zinc-100">
            <div
              className="h-full bg-zinc-900 transition-all"
              style={{ width: `${coreCompletion.total ? (coreCompletion.answered / coreCompletion.total) * 100 : 0}%` }}
            />
          </div>
          {supplementalCompletion.total > 0 && (
            <div className="mt-4 text-sm text-zinc-600">
              补充模块 {supplementalCompletion.answered}/{supplementalCompletion.total}
            </div>
          )}
        </section>

        <nav className="rounded-lg border border-zinc-200 bg-white p-2">
          {instruments.map((instrument) => {
            const answered = (answers[instrument.code] || []).filter((value) => value !== null).length
            const active = instrument.code === effectiveActiveCode
            return (
              <button
                key={instrument.code}
                type="button"
                onClick={() => setActiveCode(instrument.code)}
                className={
                  active
                    ? 'mb-1 w-full rounded-md bg-zinc-900 px-3 py-2 text-left text-sm text-white'
                    : 'mb-1 w-full rounded-md px-3 py-2 text-left text-sm text-zinc-700 hover:bg-zinc-100'
                }
              >
                <span className="block font-medium">{instrument.title}</span>
                <span className={active ? 'mt-1 block text-xs text-zinc-200' : 'mt-1 block text-xs text-zinc-500'}>
                  {answered}/{instrument.questions.length}
                </span>
              </button>
            )
          })}

          {visibleSupplementalModules.length > 0 && (
            <div className="mt-2 border-t border-zinc-100 pt-2">
              {visibleSupplementalModules.map((module) => {
                const answered = (supplementAnswers[module.code] || []).filter((value) => value !== null).length
                const active = module.code === effectiveActiveCode
                return (
                  <button
                    key={module.code}
                    type="button"
                    onClick={() => setActiveCode(module.code)}
                    className={
                      active
                        ? 'mb-1 w-full rounded-md bg-zinc-900 px-3 py-2 text-left text-sm text-white'
                        : 'mb-1 w-full rounded-md px-3 py-2 text-left text-sm text-zinc-700 hover:bg-zinc-100'
                    }
                  >
                    <span className="block font-medium">{module.title}</span>
                    <span className={active ? 'mt-1 block text-xs text-zinc-200' : 'mt-1 block text-xs text-zinc-500'}>
                      {answered}/{module.questions.length}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </nav>

        <section className="rounded-lg border border-zinc-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-zinc-900">最近状态</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-600">
            {snapshot?.summary || '暂无状态筛查记录。'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className={`rounded-full border px-2 py-1 text-xs ${stageTone(snapshot?.stage)}`}>
              {stageCopy(snapshot?.stage)}
            </span>
            <span className="rounded-full border border-zinc-200 px-2 py-1 text-xs text-zinc-600">
              置信度 {confidenceCopy(snapshot?.confidence)}
            </span>
          </div>
          <p className="mt-3 text-xs text-zinc-500">{formatDate(snapshot?.updated_at)}</p>
        </section>
      </aside>

      <section className="space-y-4">
        {phqSelfHarmPositive && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
            PHQ-9 第 9 题提示你最近出现过死亡或自伤相关想法。请优先联系身边可信任的人、当地紧急服务或专业人员；如果有立即危险，请马上寻求紧急帮助。
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {notice && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            {notice}
          </div>
        )}

        {activeInstrument && (
          <section className="rounded-lg border border-zinc-200 bg-white">
            <div className="border-b border-zinc-200 p-5">
              <h2 className="text-lg font-semibold text-zinc-900">{activeInstrument.title}</h2>
              <p className="mt-2 text-sm leading-6 text-zinc-600">{activeInstrument.subtitle}</p>
            </div>

            <div className="divide-y divide-zinc-100">
              {activeInstrument.questions.map((question, index) => (
                <div key={`${activeInstrument.code}-${index}`} className="grid gap-3 p-5">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-medium text-zinc-700">
                      {index + 1}
                    </span>
                    <p className="text-sm leading-6 text-zinc-900">{question}</p>
                  </div>

                  {activeInstrument.code === 'des2' ? (
                    <select
                      value={answers[activeInstrument.code]?.[index] ?? ''}
                      onChange={(event) =>
                        setAnswer(activeInstrument.code, index, Number(event.target.value))
                      }
                      className="ml-10 w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-300 sm:w-56"
                    >
                      <option value="">选择比例</option>
                      {activeInstrument.options.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="ml-10 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                      {activeInstrument.options.map((option) => {
                        const checked = answers[activeInstrument.code]?.[index] === option.value
                        return (
                          <label
                            key={option.value}
                            className={
                              checked
                                ? 'flex min-h-11 cursor-pointer items-center rounded-lg border border-zinc-900 bg-zinc-900 px-3 py-2 text-sm text-white'
                                : 'flex min-h-11 cursor-pointer items-center rounded-lg border border-zinc-200 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-50'
                            }
                          >
                            <input
                              type="radio"
                              name={`${activeInstrument.code}-${index}`}
                              value={option.value}
                              checked={checked}
                              onChange={() => setAnswer(activeInstrument.code, index, option.value)}
                              className="sr-only"
                            />
                            {option.label}
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {activeSupplementalModule && (
          <section className="rounded-lg border border-zinc-200 bg-white">
            <div className="border-b border-zinc-200 p-5">
              <h2 className="text-lg font-semibold text-zinc-900">{activeSupplementalModule.title}</h2>
              <p className="mt-2 text-sm leading-6 text-zinc-600">{activeSupplementalModule.subtitle}</p>
            </div>

            <div className="divide-y divide-zinc-100">
              {activeSupplementalModule.questions.map((question, index) => (
                <div key={`${activeSupplementalModule.code}-${question.code}`} className="grid gap-3 p-5">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-medium text-zinc-700">
                      {index + 1}
                    </span>
                    <p className="text-sm leading-6 text-zinc-900">{question.prompt}</p>
                  </div>

                  <div className="ml-10 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    {question.options.map((option) => {
                      const checked = supplementAnswers[activeSupplementalModule.code]?.[index] === option.value
                      return (
                        <label
                          key={option.value}
                          className={
                            checked
                              ? 'flex min-h-11 cursor-pointer items-center rounded-lg border border-zinc-900 bg-zinc-900 px-3 py-2 text-sm text-white'
                              : 'flex min-h-11 cursor-pointer items-center rounded-lg border border-zinc-200 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-50'
                          }
                        >
                          <input
                            type="radio"
                            name={`${activeSupplementalModule.code}-${question.code}`}
                            value={option.value}
                            checked={checked}
                            onChange={() => setSupplementAnswer(activeSupplementalModule.code, index, option.value)}
                            className="sr-only"
                          />
                          {option.label}
                        </label>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="rounded-lg border border-zinc-200 bg-white p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-zinc-500">
              {!coreComplete
                ? '请先完成四个核心量表。'
                : supplementalComplete
                  ? '核心量表和已触发的补充模块均已完成。'
                  : '请完成自动出现的补充模块后提交。'}
            </p>
            <button
              type="button"
              onClick={submitAll}
              disabled={!canSubmit || submitting}
              className="rounded-lg bg-zinc-900 px-5 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
            >
              {submitting ? '保存中...' : '提交状态评估'}
            </button>
          </div>
        </section>

        {orderedResults.length > 0 && (
          <section id="assessment-results" className="rounded-lg border border-zinc-200 bg-white p-5">
            <div className="flex flex-col gap-2 border-b border-zinc-200 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-zinc-900">评估结果</h2>
                <p className="mt-1 text-sm text-zinc-600">筛查提示已保存为最近状态快照，不作为医疗诊断。</p>
              </div>
              <span className={`w-fit rounded-full border px-3 py-1 text-xs ${stageTone(snapshot?.stage)}`}>
                {stageCopy(snapshot?.stage)}
              </span>
            </div>

            {(snapshot?.safety?.flags || []).includes('current_safety_urgent') && (
              <div className="mt-4 rounded-lg border border-red-300 bg-red-50 p-4 text-sm leading-6 text-red-950">
                <h3 className="font-semibold">请先保证眼前安全</h3>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  <li>如果危险正在发生，请立即拨打 110 或 120。</li>
                  <li>远离刀具、药物、绳索、高处或其他可能造成伤害的物品和地点。</li>
                  <li>不要独处，立即联系一位可信任的人陪在你身边。</li>
                </ul>
                <p className="mt-2 font-medium">
                  人工安全值守时间为工作日 09:00–18:00（中国时间）；其他时段无人实时查看。
                </p>
              </div>
            )}

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-zinc-200 p-4">
                <h3 className="text-sm font-semibold text-zinc-900">风险阶段</h3>
                <p className="mt-3 text-2xl font-semibold text-zinc-900">{stageCopy(snapshot?.stage)}</p>
                <p className="mt-2 text-sm text-zinc-600">{riskCopy(snapshot?.safety?.risk_level)}</p>
              </div>
              <div className="rounded-lg border border-zinc-200 p-4">
                <h3 className="text-sm font-semibold text-zinc-900">置信度</h3>
                <p className="mt-3 text-2xl font-semibold text-zinc-900">{confidenceCopy(snapshot?.confidence)}</p>
                <p className="mt-2 text-sm text-zinc-600">由核心量表和已完成补充模块综合判断。</p>
              </div>
              <div className="rounded-lg border border-zinc-200 p-4">
                <h3 className="text-sm font-semibold text-zinc-900">趋势</h3>
                <p className="mt-3 text-2xl font-semibold text-zinc-900">{trendCopy(snapshot?.trend)}</p>
                <p className="mt-2 text-sm text-zinc-600">仅在存在历史快照时用于参考。</p>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {orderedResults.map((result) => (
                <article key={result.instrument} className="rounded-lg border border-zinc-200 p-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <h3 className="text-sm font-semibold text-zinc-900">{result.title}</h3>
                    <span className={`w-fit rounded-full border px-2 py-1 text-xs ${severityTone(result.severity)}`}>
                      {result.label}
                    </span>
                  </div>
                  <p className="mt-3 text-2xl font-semibold text-zinc-900">{result.score}</p>
                  <p className="mt-2 text-sm leading-6 text-zinc-600">{result.recommendation}</p>
                  <p className="mt-3 text-xs leading-5 text-zinc-500">{result.disclaimer}</p>
                </article>
              ))}
            </div>
          </section>
        )}
      </section>
    </div>
  )
}
