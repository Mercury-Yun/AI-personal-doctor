/** 与 backend/services/medication_intent.py 保持一致的轻量规则，用于前端秒级判定 */

const PHOTO_HINTS = [
  '拍照',
  '问药',
  '识药',
  '药盒',
  '看看药',
  '拍药',
  '识别药',
  '什么药',
  '这是什么药',
  '药名',
  '包装上',
]

// "这是什么/那是什么"需要药上下文才触发
const POINTER_WHAT_DRUG_ONLY = ['这是什么', '这是啥', '那是什么', '那是啥']

// 健康对话排除词——含这些词时不应触发拍照
const HEALTH_CONTEXT_WORDS = [
  '症状', '病', '原因', '情况', '指标', '问题', '怎么办',
  '治疗', '为什么', '怎么回事', '疼', '痛', '检查', '报告',
  '血压', '血糖', '心脏', '头晕', '发烧', '咳嗽',
]

const USAGE_HINTS = [
  '怎么吃',
  '如何用',
  '用法',
  '用量',
  '一天',
  '几次',
  '饭前',
  '饭后',
  '副作用',
  '禁忌',
  '注意',
  '能吃吗',
]

const EXPLICIT_PHOTO = [
  '拍照',
  '问药',
  '识药',
  '药盒',
  '看看药',
  '拍药',
  '识别药',
  '什么药',
  '这是什么药',
  '包装上',
]

const POINTER_WORDS = ['这个', '那个', '这盒', '那盒', '它', '上面', '包装上']
const VISUAL_VERBS = ['看', '瞧', '认', '读', '拍', '识别']

function isDrugUsageQuestion(text) {
  return USAGE_HINTS.some((h) => text.includes(h))
}

function isExplicitPhotoRequest(text) {
  if (EXPLICIT_PHOTO.some((h) => text.includes(h))) return true
  // "这是什么" + 药上下文
  if (POINTER_WHAT_DRUG_ONLY.some((p) => text.includes(p))) {
    if (text.includes('药')) return true
    if (!HEALTH_CONTEXT_WORDS.some((w) => text.includes(w))) return true
  }
  return false
}

function isMedicationVerifyQuestion(text) {
  const verifyHints = ['是不是这个药', '是这个药', '该吃这个', '该吃吗', '拿对了', '拿错', '核实', '比对']
  if (verifyHints.some((h) => text.includes(h))) return true
  if (text.includes('药') && POINTER_WORDS.some((p) => text.includes(p))) {
    return text.endsWith('吗') || text.endsWith('嘛') || text.includes('是不是')
  }
  return false
}

/** 本地快速判定是否应切到拍照问药（明显场景无需等 API） */
export function isPhotoIntent(text) {
  const normalized = (text || '').trim()
  if (!normalized) return false

  // 健康上下文检测
  const hasHealthContext = HEALTH_CONTEXT_WORDS.some((w) => normalized.includes(w))

  if (isDrugUsageQuestion(normalized) && !isExplicitPhotoRequest(normalized)) {
    return false
  }
  if (isMedicationVerifyQuestion(normalized)) return true
  if (PHOTO_HINTS.some((h) => normalized.includes(h))) {
    // "吃什么药好/该吃什么药" 是用药咨询，不是拍照
    if (normalized.includes('什么药') && ['吃', '用', '服', '该'].some((w) => normalized.includes(w))) {
      return false
    }
    return true
  }

  // "这是什么/那是什么"需要药上下文
  if (POINTER_WHAT_DRUG_ONLY.some((p) => normalized.includes(p))) {
    if (normalized.includes('药')) return true
    if (hasHealthContext) return false
    return normalized.length <= 6
  }

  const asksWhat = normalized.includes('什么') || normalized.includes('啥') || normalized.includes('哪个')
  const hasPointer = POINTER_WORDS.some((w) => normalized.includes(w))
  const hasVisual = VISUAL_VERBS.some((v) => normalized.includes(v))

  // 组合规则：必须含"药"相关词才触发
  const hasDrugContext = normalized.includes('药') ||
    ['药盒', '包装', '生产日期', '保质期', '有效期', '批号'].some((w) => normalized.includes(w))

  if (hasHealthContext) return false

  if (hasVisual && hasDrugContext && (hasPointer || asksWhat)) return true
  if (hasPointer && hasDrugContext && asksWhat) return true

  return false
}

export async function resolvePhotoIntent(text, classifyIntentApi) {
  if (isPhotoIntent(text)) return true
  try {
    const { data } = await classifyIntentApi(text)
    return data.intent === 'photo'
  } catch {
    return false
  }
}
