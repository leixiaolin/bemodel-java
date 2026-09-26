<template>
  <div class="page ask-page">
    <!-- 左：对话流 -->
    <div class="chat-col">
      <div ref="flowRef" class="chat-flow">
        <!-- 欢迎态 -->
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-icon"><el-icon :size="30"><ChatDotRound /></el-icon></div>
          <div class="welcome-title">智能问数</div>
          <div class="welcome-desc">
            基于本体语义层回答数据问题：AI 把问题解析为「概念 → 关系 → 物理表」的查询计划，
            SQL 经白名单校验后在业务库实时执行——数字来自真实查询，解析过程完全可解释。
          </div>
          <div class="sq-suggests">
            <div class="sq-suggests-title">试试这样问</div>
            <div class="sq-suggests-list">
              <button v-for="s in suggestions" :key="s" class="sq-chip" @click="ask(s)">{{ s }}</button>
            </div>
          </div>
        </div>

        <!-- 消息流 -->
        <template v-for="(msg, i) in messages" :key="i">
          <div v-if="msg.role === 'user'" class="msg msg-user">
            <div class="bubble bubble-user">{{ msg.text }}</div>
          </div>
          <div v-else class="msg msg-ai">
            <div class="ai-avatar">Bm</div>
            <div class="bubble bubble-ai">
              <!-- 增长回路卡：语义层答不了，已回流概念缺口 -->
              <template v-if="msg.unanswered">
                <div class="unans-card">
                  <div class="unans-title"><el-icon><Opportunity /></el-icon> 这个问题超出了当前本体的覆盖范围</div>
                  <div class="unans-body">{{ msg.text }}</div>
                  <div class="unans-foot">
                    已自动记录为概念缺口提案，热度会随提问次数增长；治理者可在概念缺口页采纳，
                    本体长出新概念后这类问题就能被语义层真正回答。
                    <el-button size="small" type="primary" plain @click="$router.push('/evolve')">
                      查看概念缺口
                    </el-button>
                  </div>
                </div>
              </template>
              <!-- 普通回答卡 -->
              <template v-else>
                <div class="ans-head">
                  <el-tag size="small" :type="routeTagType(msg.router)" effect="plain">
                    {{ routeText(msg.router) }}
                  </el-tag>
                  <span class="ans-intent">{{ msg.intent }}</span>
                  <el-icon
                    v-if="msg.parse"
                    class="parse-jump"
                    :class="{ active: activeIdx === i }"
                    title="在右侧查看语义解析"
                    @click="focusParse(i)"
                  ><DataLine /></el-icon>
                </div>
                <!-- 口径卡：指标命中时结构化展示（定义/公式/探针SQL 均来自指标库真实数据） -->
                <template v-if="msg.card === 'METRIC' && msg.metric">
                  <div class="metric-card">
                    <div class="mc-head">
                      <span class="mc-name">{{ msg.metric.name }}</span>
                      <span class="mc-code">{{ msg.metric.metricCode }}</span>
                      <el-tag v-if="msg.metric.hasProbe" size="small" type="success" effect="plain">已接入巡检</el-tag>
                    </div>
                    <div class="mc-row"><b>口径定义</b><span>{{ msg.metric.definition || '-' }}</span></div>
                    <div class="mc-row"><b>计算公式</b><pre class="mc-formula">{{ msg.metric.formula || '-' }}</pre></div>
                    <template v-if="msg.metric.probeSql">
                      <div class="mc-probe-head">探针 SQL（与指标巡检同一执行来源）</div>
                      <pre class="sql-code">{{ msg.metric.probeSql }}</pre>
                    </template>
                    <div class="mc-foot">
                      <span>负责人：{{ msg.metric.owner || '-' }}</span>
                      <span v-if="msg.metric.hasProbe && msg.metric.lastVal != null">
                        上次巡检值 {{ msg.metric.lastVal }}<template v-if="msg.metric.lastEvalAt">（{{ msg.metric.lastEvalAt }}）</template>
                      </span>
                      <span v-else-if="msg.metric.hasProbe">暂无实测值，可在统一口径页执行检测</span>
                      <span v-else>该指标未接入实测监控（需配置数据源+探针 SQL）</span>
                    </div>
                    <div v-if="msg.text" class="mc-llm">{{ msg.text }}</div>
                  </div>
                </template>
                <div v-else class="ans-body">{{ msg.text }}</div>
                <div v-if="msg.evidence?.length" class="ans-evidence">
                  <div v-for="(e, j) in msg.evidence" :key="j" class="ans-evidence-item">
                    <b>{{ e.label }}</b>
                    <span class="evidence-value">{{ e.value }}</span>
                  </div>
                </div>
                <div v-if="msg.links?.length" class="ans-links">
                  <el-button
                    v-for="(l, j) in msg.links"
                    :key="j"
                    size="small"
                    link
                    type="primary"
                    @click="$router.push(l.route)"
                  >{{ l.label }} →</el-button>
                </div>
              </template>
            </div>
          </div>
        </template>
        <div v-if="asking" class="msg msg-ai">
          <div class="ai-avatar">Bm</div>
          <div class="bubble bubble-ai thinking">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            正在解析语义并生成查询计划…
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="chat-input">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="输入数据问题，Enter 发送（Shift+Enter 换行）"
          :disabled="asking"
          @keydown.enter.exact.prevent="send"
        />
        <el-button type="primary" :loading="asking" :disabled="!input.trim()" @click="send">
          <el-icon v-if="!asking"><Promotion /></el-icon>&nbsp;提问
        </el-button>
      </div>
    </div>

    <!-- 右：语义解析面板 -->
    <div class="parse-col" :class="{ empty: !activeParse }">
      <template v-if="activeParse">
        <div class="parse-head">
          <span class="parse-title"><el-icon><DataLine /></el-icon> 语义解析</span>
          <span class="parse-sub">来自最近一次语义查询</span>
        </div>

        <!-- 1. 概念匹配 -->
        <div class="parse-block">
          <div class="block-title">① 概念匹配</div>
          <div v-if="activeParse.matchedConcepts?.length" class="concept-chips">
            <el-tag
              v-for="c in activeParse.matchedConcepts"
              :key="c.code"
              class="concept-chip"
              effect="plain"
              @click="$router.push({ path: '/ontology', query: { concept: c.code } })"
            >
              {{ c.name }}<span class="chip-code">{{ c.code }}</span>
              <span class="chip-match">{{ c.match }}</span>
            </el-tag>
          </div>
          <div v-else class="block-empty">问题未命中已发布概念</div>
        </div>

        <!-- 2. 关联概念关系（命中概念在本体中的邻域，非 SQL 实际路径） -->
        <div class="parse-block">
          <div class="block-title">② 关联概念关系</div>
          <div v-if="activeParse.relations?.length" class="rel-chain">
            <div v-for="(r, i) in activeParse.relations" :key="i" class="rel-item">
              <span class="rel-node">{{ r.fromName }}</span>
              <span class="rel-arrow">—{{ r.relation }}→</span>
              <span class="rel-node">{{ r.toName }}</span>
              <el-tag class="rel-tag" size="small" effect="plain" :type="r.used ? 'success' : 'info'">
                {{ r.used ? '本次查询' : '本体相邻' }}
              </el-tag>
            </div>
            <div v-if="activeParse.relations.some((r) => !r.used)" class="rel-note">
              「本体相邻」＝本体中与命中概念相连的关系，本次 SQL 未实际使用
            </div>
          </div>
          <div v-else class="block-empty">无关联关系</div>
        </div>

        <!-- 3. 查询逻辑 -->
        <div class="parse-block">
          <div class="block-title">③ 查询逻辑</div>
          <div v-if="activeParse.semantics" class="semantics-text">{{ activeParse.semantics }}</div>
          <div v-if="activeParse.sql" class="sql-fold">
            <div class="sql-fold-head" @click="sqlOpen = !sqlOpen">
              <el-icon><component :is="sqlOpen ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
              执行 SQL（白名单校验后真实执行）
            </div>
            <pre v-show="sqlOpen" class="sql-code">{{ activeParse.sql }}</pre>
          </div>
          <div v-if="activeParse.rows?.length" class="rows-preview">
            <el-table :data="activeParse.rows" size="small" border max-height="240">
              <el-table-column
                v-for="col in rowColumns"
                :key="col"
                :prop="col"
                :label="col"
                show-overflow-tooltip
                min-width="90"
              />
            </el-table>
            <div class="rows-tip">最多展示前 20 行，完整结果以回答中的统计为准</div>
          </div>
        </div>

        <!-- 4. 智能体纠错（执行结果可疑时由校验纠错智能体诊断修正，仅修正被采用时展示） -->
        <div v-if="activeParse.corrections?.length" class="parse-block">
          <div class="block-title">④ 智能体纠错</div>
          <div class="fix-list">
            <div v-for="(c, i) in activeParse.corrections" :key="i" class="fix-item">
              <div class="fix-reason">{{ c.reason }}</div>
              <pre class="sql-code fix-sql">{{ c.before }}</pre>
              <div class="fix-arrow">↓ 修正为</div>
              <pre class="sql-code fix-sql">{{ c.after }}</pre>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="parse-empty">
        <el-icon :size="28"><DataLine /></el-icon>
        <div>{{ parseEmptyHint }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { askCs } from '../../api/cs'
import { ChatDotRound, Opportunity, Promotion, DataLine, ArrowDown, ArrowRight } from '@element-plus/icons-vue'

// 建议问题：问数场景样例（口径/明细/统计），与 AI 客服页（服务处置样例）零重叠
const suggestions = [
  '出院人数怎么算？',
  '最近10条缴费记录',
  '昨天缴费总额是多少？',
  '退费金额有多少？',
  '住院患者有多少人？',
  '住院患者名单'
]

const ROUTE_TEXT = { RULE: '规则路由', LLM: 'AI 归类', SEMANTIC: '语义查询', REFERRAL: '场景转介', NONE: '能力菜单' }
const ROUTE_TYPE = { RULE: 'warning', LLM: 'warning', SEMANTIC: 'success', REFERRAL: 'warning', NONE: 'info' }
const routeText = (r) => ROUTE_TEXT[r] || r || '回答'
const routeTagType = (r) => ROUTE_TYPE[r] || 'info'

const route = useRoute()
const input = ref('')
const asking = ref(false)
const messages = ref([]) // {role:'user'|'ai', text, router, intent, evidence, links, parse, unanswered, card, metric}
const activeIdx = ref(-1) // 当前解析面板展示的消息下标
const sqlOpen = ref(false)
const flowRef = ref(null)

const activeParse = computed(() =>
  activeIdx.value >= 0 ? messages.value[activeIdx.value]?.parse : null
)
const rowColumns = computed(() =>
  activeParse.value?.rows?.length ? Object.keys(activeParse.value.rows[0]) : []
)

// 右栏空态提示：按最近一条回答的真实状态如实说明，不过度承诺、不断言后端配置
const parseEmptyHint = computed(() => {
  const last = [...messages.value].reverse().find((m) => m.role === 'ai')
  if (!last) return '提问后，语义查询类回答会在这里展示解析过程：命中概念、关联关系、查询逻辑与原始行数据'
  if (last.unanswered) return '这个问题超出了当前本体的覆盖，暂无解析可展示；本体采纳该缺口后即可被语义层回答'
  if (last.card === 'METRIC') return '口径类回答以左侧指标卡展示：定义、公式与探针 SQL 均来自指标库真实数据；数据类问题（如「最近10条缴费记录」）可展示完整语义解析'
  if (last.router === 'REFERRAL') return '这个问题未命中问数场景能力，可按左侧回答里的入口转 AI 客服，或换个数据问法（如「最近10条缴费记录」）'
  return '这条回答走的是「' + routeText(last.router) + '」，未产生语义解析；数据类问题（如「最近10条缴费记录」）可展示完整解析'
})

const scrollToBottom = () => {
  nextTick(() => {
    if (flowRef.value) flowRef.value.scrollTop = flowRef.value.scrollHeight
  })
}

const focusParse = (i) => {
  activeIdx.value = i
  sqlOpen.value = false
}

const send = () => ask(input.value)

// 承接跨页转介深链（如 AI 客服页「找数据？去智能问数」带原问题跳入）
onMounted(() => {
  const q0 = route.query.q
  if (q0) ask(String(q0))
})

const ask = async (q) => {
  q = (q || '').trim()
  if (!q || asking.value) return
  input.value = ''
  messages.value.push({ role: 'user', text: q })
  scrollToBottom()
  asking.value = true
  try {
    const res = await askCs(q, 'ANALYTICS')
    // 语义层答不了（已回流增长回路）→ 增长回路卡；missRecorded 为后端显式标记，不做字符串嗅探
    const unanswered = res.missRecorded === true
      || (!res.router && typeof res.answer === 'string' && res.answer.includes('本体完善提案'))
    // 口径卡回答：结构化内容交给卡片，正文只保留 LLM 自然语言解读，避免与卡片重复
    const isCard = res.card === 'METRIC' && !!res.metric
    const msg = {
      role: 'ai',
      text: isCard ? res.answerLlm || '' : res.answer,
      card: res.card,
      metric: res.metric,
      router: res.router,
      intent: res.intent,
      evidence: res.evidence,
      links: res.links,
      unanswered
    }
    // 语义查询 → 组装右侧解析面板（概念/关系/查询逻辑/原始行，全部来自真实结构）
    if (res.router === 'SEMANTIC') {
      const sqlEv = (res.evidence || []).find((e) => e.label === '执行SQL')
      msg.parse = {
        matchedConcepts: res.matchedConcepts || [],
        relations: res.relations || [],
        semantics: res.semantics,
        sql: sqlEv?.value,
        rows: res.rows || [],
        corrections: res.corrections || []
      }
    }
    messages.value.push(msg)
    if (msg.parse) focusParse(messages.value.length - 1)
  } catch (e) {
    messages.value.push({
      role: 'ai',
      text: '这次回答失败了：' + (e?.message || '网络异常') + '。请稍后重试，或换个问法。'
    })
  } finally {
    asking.value = false
    scrollToBottom()
  }
}
</script>

<style scoped>
.ask-page {
  display: flex;
  gap: 14px;
  height: calc(100vh - var(--topbar-height) - 48px);
}

/* ---------- 左：对话列 ---------- */
.chat-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.chat-flow {
  flex: 1;
  overflow-y: auto;
  padding: 20px 22px;
}

/* 欢迎态 */
.welcome {
  max-width: 560px;
  margin: 6vh auto 0;
  text-align: center;
}

.welcome-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 14px;
  border-radius: 16px;
  background: linear-gradient(135deg, var(--primary), #4db6ac);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.welcome-title {
  font-size: 20px;
  font-weight: 700;
}

.welcome-desc {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.sq-suggests {
  margin-top: 26px;
}

.sq-suggests-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.sq-suggests-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.sq-chip {
  border: 1px solid var(--border-color);
  background: var(--card-bg);
  border-radius: 16px;
  padding: 6px 14px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: var(--transition);
}

.sq-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-light, rgba(45, 138, 126, 0.06));
}

/* 消息 */
.msg {
  display: flex;
  margin-bottom: 16px;
}

.msg-user {
  justify-content: flex-end;
}

.bubble {
  max-width: 78%;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.bubble-user {
  background: var(--primary);
  color: #fff;
  border-bottom-right-radius: 3px;
}

.bubble-ai {
  background: var(--el-bg-color-page, #f7f8fa);
  border: 1px solid var(--border-color);
  border-bottom-left-radius: 3px;
}

.ai-avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--primary), #4db6ac);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 10px;
  flex-shrink: 0;
  align-self: flex-start;
}

/* 思考中 */
.thinking {
  color: var(--text-muted);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 3px;
}

.thinking .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--primary);
  animation: blink 1.2s infinite;
}

.thinking .dot:nth-child(2) {
  animation-delay: 0.2s;
}

.thinking .dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%, 70%, 100% { opacity: 0.25; }
  35% { opacity: 1; }
}

/* 回答卡内部 */
.ans-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.ans-intent {
  font-size: 12px;
  color: var(--text-muted);
}

.parse-jump {
  margin-left: auto;
  cursor: pointer;
  color: var(--text-muted);
}

.parse-jump.active {
  color: var(--primary);
}

.ans-evidence {
  margin-top: 8px;
  border-top: 1px dashed var(--border-color);
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ans-evidence-item {
  font-size: 12px;
  color: var(--text-secondary);
}

.ans-evidence-item b {
  color: var(--text-primary);
  margin-right: 6px;
}

.evidence-value {
  word-break: break-all;
}

.ans-links {
  margin-top: 8px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

/* 口径卡（指标命中） */
.metric-card {
  margin-top: 8px;
  border: 1px solid var(--el-color-success-light-5, #b3e19d);
  background: var(--el-color-success-light-9, #f0f9eb);
  border-radius: 8px;
  padding: 12px 14px;
}

.mc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mc-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-primary);
}

.mc-code {
  font-size: 11px;
  color: var(--text-muted);
}

.mc-row {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.mc-row b {
  color: var(--text-primary);
  margin-right: 8px;
}

.mc-formula {
  margin: 4px 0 0;
  padding: 8px 10px;
  background: var(--el-bg-color-page, #f7f8fa);
  border-radius: 6px;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
}

.mc-probe-head {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.mc-foot {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}

.mc-llm {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-secondary);
}

/* 增长回路卡 */
.unans-card {
  border: 1px solid var(--el-color-warning-light-5, #f3d19e);
  background: var(--el-color-warning-light-9, #fdf6ec);
  border-radius: 8px;
  padding: 12px 14px;
}

.unans-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--el-color-warning);
}

.unans-body {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.unans-foot {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

/* 输入区 */
.chat-input {
  display: flex;
  gap: 10px;
  padding: 14px 16px;
  border-top: 1px solid var(--border-color);
  align-items: flex-end;
}

.chat-input .el-button {
  height: 54px;
}

/* ---------- 右：解析面板 ---------- */
.parse-col {
  width: 360px;
  flex-shrink: 0;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  overflow-y: auto;
}

.parse-col.empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.parse-empty {
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.8;
  padding: 0 20px;
}

.parse-empty .el-icon {
  color: var(--border-color);
  margin-bottom: 8px;
}

.parse-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
}

.parse-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
}

.parse-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.parse-block {
  margin-bottom: 16px;
}

.block-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.block-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 6px 0;
}

/* 概念 chips */
.concept-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.concept-chip {
  cursor: pointer;
}

.chip-code {
  margin-left: 4px;
  font-size: 11px;
  opacity: 0.7;
}

.chip-match {
  margin-left: 4px;
  font-size: 10px;
  color: var(--primary);
}

/* 关联概念关系 */
.rel-chain {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rel-item {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.rel-node {
  background: var(--el-color-success-light-9, #f0f9eb);
  border-radius: 4px;
  padding: 2px 8px;
  color: var(--text-primary);
}

.rel-arrow {
  color: var(--primary);
  font-size: 11px;
}

.rel-tag {
  flex-shrink: 0;
}

.rel-note {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* 查询逻辑 */
.semantics-text {
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
  background: var(--el-bg-color-page, #f7f8fa);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
}

.sql-fold-head {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.sql-fold-head:hover {
  color: var(--primary);
}

.sql-code {
  margin: 8px 0 0;
  padding: 10px;
  background: #1e293b;
  color: #a5f3fc;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.rows-preview {
  margin-top: 10px;
}

.rows-tip {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

/* 智能体纠错 */
.fix-item {
  margin-bottom: 10px;
}

.fix-item:last-child {
  margin-bottom: 0;
}

.fix-reason {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.fix-sql {
  margin: 0;
}

.fix-arrow {
  font-size: 11px;
  color: var(--primary);
  margin: 4px 0;
}

/* 窄屏折叠解析面板 */
@media (max-width: 1100px) {
  .parse-col {
    display: none;
  }
}
</style>
