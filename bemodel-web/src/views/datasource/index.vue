<template>
  <div class="page">
    <!-- 数据源卡片行 -->
    <div class="ds-cards" v-loading="loadingDs">
      <el-card
        v-for="ds in datasources"
        :key="ds.dsCode"
        class="ds-card"
        :class="{ active: currentDs?.dsCode === ds.dsCode, disabled: isDisabled(ds) }"
        shadow="hover"
        @click="selectDs(ds)"
      >
        <div class="ds-title">
          <span>{{ ds.dsName }}</span>
          <el-tag v-if="isDisabled(ds)" size="small" type="warning" effect="plain">已失效</el-tag>
        </div>
        <div class="ds-meta">产品：{{ ds.productName }}</div>
        <div class="ds-meta">{{ ds.dbType }} · {{ ds.host }}:{{ ds.port }}/{{ ds.dbName }}</div>
        <div class="ds-meta">账号：{{ ds.username }}</div>
        <div v-if="!userStore.isViewer" class="ds-actions">
          <el-button
            size="small"
            :disabled="isDisabled(ds)"
            :loading="scanningDs === ds.dsCode"
            @click.stop="doScan(ds)"
          >扫描</el-button>
          <el-button
            size="small"
            :loading="togglingDs === ds.dsCode"
            @click.stop="toggleStatus(ds)"
          >{{ isDisabled(ds) ? '激活' : '失效' }}</el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :loading="deletingDs === ds.dsCode"
            @click.stop="doDelete(ds)"
          >删除</el-button>
        </div>
      </el-card>

      <!-- 新增数据源入口（只读角色不可见） -->
      <el-card v-if="!userStore.isViewer" class="ds-card add-card" shadow="never" @click="openCreate">
        <div class="add-inner">
          <span class="add-plus">+</span>
          <span>新增数据源</span>
        </div>
      </el-card>
    </div>

    <template v-if="currentDs">
      <el-card class="governance-card" style="margin-top: 16px">
        <template #header>
          <div class="card-header">
            <span>AI 本体治理分析</span>
            <div>
              <el-button size="small" :loading="analysisLoading" @click="loadAnalysis">刷新</el-button>
              <el-button
                v-if="!userStore.isViewer"
                size="small"
                type="primary"
                :disabled="isDisabled(currentDs)"
                :loading="analysisStarting"
                @click="restartAnalysis"
              >重新分析</el-button>
            </div>
          </div>
        </template>
        <el-empty v-if="!analysis" description="尚无治理分析；扫描数据源后将自动创建任务" :image-size="56" />
        <template v-else>
          <div class="analysis-summary">
            <el-tag :type="analysisStatusType(analysis.status)">{{ analysisStatusText(analysis.status) }}</el-tag>
            <span>任务 #{{ analysis.id }}</span>
            <span>进度 {{ analysis.progress || 0 }}%</span>
            <span v-if="analysis.model">模型：{{ analysis.model }}</span>
            <span v-if="analysis.changeSet?.suggestionCount">建议 {{ analysis.changeSet.suggestionCount }} 项</span>
            <span v-if="analysis.changeSet?.highRiskCount">高风险 {{ analysis.changeSet.highRiskCount }} 项</span>
          </div>
          <el-progress
            v-if="['PENDING', 'RUNNING'].includes(analysis.status)"
            :percentage="analysis.progress || 0"
            :status="analysis.status === 'RUNNING' ? undefined : 'warning'"
            style="margin-top: 12px"
          />
          <el-alert
            v-if="analysis.errorMessage"
            :title="analysis.errorMessage"
            :type="analysis.status === 'FAILED' ? 'error' : 'warning'"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
          <div v-if="analysis.changeSet" class="analysis-actions">
            <span v-if="analysis.changeSet.summary?.mappingCoverage !== undefined">
              当前映射覆盖率 {{ Math.round(analysis.changeSet.summary.mappingCoverage * 100) }}%
            </span>
            <el-button type="success" plain @click="openGovernanceWorkbench">审核变更集</el-button>
          </div>
        </template>
      </el-card>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="8">
          <el-card>
            <template #header>
              <span>物理表（{{ currentDs.dsCode }}）</span>
            </template>
            <el-table
              :data="tables"
              v-loading="loadingTables"
              highlight-current-row
              height="540"
              @row-click="selectTable"
            >
              <el-table-column prop="tableName" label="表名" width="160" />
              <el-table-column prop="tableComment" label="注释" show-overflow-tooltip />
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="16">
          <el-card v-if="currentTable">
            <template #header>
              <div class="card-header">
                <span>
                  映射工作台：{{ currentTable }}
                  <el-tag
                    v-if="aiMeta"
                    size="small"
                    style="margin-left: 8px"
                    :type="aiMeta.llmUsed ? 'success' : 'info'"
                    effect="plain"
                  >
                    {{ aiMeta.llmUsed ? `AI生成（${aiMeta.model}）` : '规则降级' }}
                  </el-tag>
                </span>
                <el-tooltip
                  :content="userStore.isViewer ? '只读角色无写权限' : '数据源已失效，激活后可操作'"
                  :disabled="!userStore.isViewer && !isDisabled(currentDs)"
                  placement="top"
                >
                  <span>
                    <el-button
                      type="primary"
                      :disabled="userStore.isViewer || isDisabled(currentDs)"
                      :loading="aiLoading"
                      @click="runAiSuggest"
                    >
                      AI 推荐映射
                    </el-button>
                  </span>
                </el-tooltip>
              </div>
            </template>
            <el-table :data="rows" v-loading="loadingColumns">
              <el-table-column label="物理列" width="150">
                <template #default="{ row }">
                  {{ row.columnName }}
                  <el-tag v-if="row.isPk === 1" size="small" type="danger" effect="plain">PK</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="dataType" label="类型" width="90" />
              <el-table-column prop="columnComment" label="注释" width="130" show-overflow-tooltip />
              <el-table-column label="当前映射" min-width="200">
                <template #default="{ row }">
                  <template v-if="row.mapping">
                    <el-tooltip
                      :disabled="!row.mapping.valueMap"
                      :content="`值映射：${row.mapping.valueMap}`"
                      placement="top"
                    >
                      <el-tag>{{ row.mapping.conceptCode }}.{{ row.mapping.attrCode }}</el-tag>
                    </el-tooltip>
                    <el-tag
                      v-if="['AI', 'AI_GOVERNANCE'].includes(row.mapping.source)"
                      size="small"
                      type="warning"
                      effect="plain"
                      style="margin-left: 4px"
                    >AI</el-tag>
                    <el-tag
                      v-if="row.mapping.confirmed === 1"
                      size="small"
                      type="success"
                      effect="plain"
                      style="margin-left: 4px"
                    >已确认</el-tag>
                  </template>
                  <el-tag v-else type="info" effect="plain">未映射</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="AI 建议" min-width="230">
                <template #default="{ row }">
                  <template v-if="row.suggestion">
                    <el-tooltip :content="row.suggestion.reason" placement="top">
                      <el-tag type="warning" effect="plain">
                        {{ row.suggestion.conceptCode }}.{{ row.suggestion.attrCode }}
                        （{{ Math.round(row.suggestion.confidence * 100) }}%）
                      </el-tag>
                    </el-tooltip>
                    <el-button
                      v-if="!userStore.isViewer"
                      size="small"
                      link
                      type="primary"
                      :disabled="row.accepted || isDisabled(currentDs)"
                      @click="accept(row)"
                    >{{ row.accepted ? '已采纳' : '采纳' }}</el-button>
                  </template>
                  <span v-else class="no-suggest">-</span>
                </template>
              </el-table-column>
              <el-table-column v-if="!userStore.isViewer" label="操作" width="110" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" :disabled="isDisabled(currentDs)" @click="openEdit(row)">编辑映射</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="footer-bar" v-if="acceptedRows.length">
              <el-button type="success" :loading="saving" :disabled="isDisabled(currentDs)" @click="saveAccepted">
                保存已采纳映射（{{ acceptedRows.length }}）
              </el-button>
            </div>
          </el-card>
          <el-card v-else>
            <el-empty description="请选择左侧物理表进行映射" />
          </el-card>
        </el-col>
      </el-row>
    </template>
    <el-card v-else style="margin-top: 16px">
      <el-empty description="请选择一个数据源" />
    </el-card>

    <el-dialog v-model="governanceVisible" title="AI 本体治理变更集" width="92%" top="4vh">
      <template v-if="changeSet">
        <div class="change-toolbar">
          <el-select v-model="changeFilters.type" clearable placeholder="元素类型" style="width: 150px">
            <el-option v-for="type in changeItemTypes" :key="type" :label="type" :value="type" />
          </el-select>
          <el-select v-model="changeFilters.risk" clearable placeholder="风险" style="width: 120px">
            <el-option label="高" value="HIGH" /><el-option label="中" value="MEDIUM" /><el-option label="低" value="LOW" />
          </el-select>
          <el-select v-model="changeFilters.status" clearable placeholder="审核状态" style="width: 140px">
            <el-option label="待审核" value="PENDING" /><el-option label="已接受" value="ACCEPTED" />
            <el-option label="已拒绝" value="REJECTED" /><el-option label="待补充" value="NEEDS_INPUT" />
          </el-select>
          <el-select v-model="changeFilters.confidence" clearable placeholder="最低置信度" style="width: 140px">
            <el-option label="≥ 90%" :value="0.9" /><el-option label="≥ 70%" :value="0.7" />
            <el-option label="≥ 50%" :value="0.5" />
          </el-select>
          <el-input v-model="changeFilters.table" clearable placeholder="来源表" style="width: 180px" />
          <span class="change-state">状态：{{ changeSet.status }} · 建议 {{ changeSet.suggestionCount }}</span>
        </div>
        <el-table
          ref="changeTableRef"
          :data="filteredChangeItems"
          v-loading="changeLoading"
          height="560"
          row-key="id"
          @selection-change="onChangeSelection"
        >
          <el-table-column type="selection" width="44" :selectable="selectableChangeItem" />
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="evidence-panel">
                <p><b>理由：</b>{{ row.reason || '-' }}</p>
                <p><b>证据：</b>{{ (row.evidence || []).join('；') || '-' }}</p>
                <p><b>依赖：</b>{{ (row.dependencies || []).join('；') || '-' }}</p>
                <p v-if="row.missingInformation"><b>待补充：</b>{{ row.missingInformation }}</p>
                <pre>{{ JSON.stringify(row.payload, null, 2) }}</pre>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="itemType" label="类型" width="100" />
          <el-table-column prop="operation" label="操作" width="160" />
          <el-table-column prop="targetKey" label="目标" min-width="210" show-overflow-tooltip />
          <el-table-column label="来源" min-width="180">
            <template #default="{ row }">{{ row.sourceTable }}{{ row.sourceColumn ? `.${row.sourceColumn}` : '' }}</template>
          </el-table-column>
          <el-table-column label="置信度" width="95">
            <template #default="{ row }">{{ Math.round((row.confidence || 0) * 100) }}%</template>
          </el-table-column>
          <el-table-column label="风险" width="80">
            <template #default="{ row }"><el-tag size="small" :type="riskTag(row.riskLevel)">{{ row.riskLevel }}</el-tag></template>
          </el-table-column>
          <el-table-column label="审核" width="110">
            <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.reviewStatus }}</el-tag></template>
          </el-table-column>
          <el-table-column v-if="!userStore.isViewer && changeMutable" label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="editChangeItem(row)">编辑</el-button>
              <el-button
                link type="success" :disabled="!selectableChangeItem(row)"
                @click="reviewChangeItem(row, 'ACCEPTED')"
              >接受</el-button>
              <el-button link type="danger" @click="reviewChangeItem(row, 'REJECTED')">拒绝</el-button>
              <el-button link type="warning" @click="reviewChangeItem(row, 'NEEDS_INPUT')">待补充</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="governanceVisible = false">关闭</el-button>
        <el-button
          v-if="!userStore.isViewer" type="primary" plain :disabled="!changeMutable || !selectedChangeItems.length"
          :loading="changeSaving" @click="adoptSelectedChanges"
        >批量采纳（{{ selectedChangeItems.length }}）</el-button>
        <el-button
          v-if="!userStore.isViewer" type="success" :disabled="!changeMutable || !acceptedChangeCount"
          :loading="changePublishing" @click="publishChanges"
        >创建草稿与候选映射</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="changeEditVisible" title="编辑治理建议" width="620px">
      <el-form label-width="90px">
        <el-form-item label="建议目标"><span>{{ editingChangeItem?.targetKey }}</span></el-form-item>
        <el-form-item label="载荷 JSON">
          <el-input v-model="changePayloadText" type="textarea" :rows="14" />
        </el-form-item>
        <el-form-item label="审核备注"><el-input v-model="changeReviewNote" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="changeEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="changeSaving" @click="saveChangeEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑映射 -->
    <el-dialog v-model="editVisible" :title="`编辑映射：${editRow?.columnName || ''}`" width="480px">
      <el-form label-width="90px">
        <el-form-item label="物理列">
          <span>{{ editRow?.columnName }}（{{ editRow?.dataType }}）</span>
        </el-form-item>
        <el-form-item label="概念">
          <el-select
            v-model="editForm.conceptCode"
            style="width: 100%"
            filterable
            placeholder="选择概念"
            @change="onConceptChange"
          >
            <el-option
              v-for="c in conceptStore.concepts"
              :key="c.code"
              :label="`${c.name}（${c.code}）`"
              :value="c.code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="属性">
          <el-select
            v-model="editForm.attrCode"
            style="width: 100%"
            placeholder="选择属性"
            :disabled="!editForm.conceptCode"
          >
            <el-option
              v-for="a in attrOptions"
              :key="a.attrCode"
              :label="`${a.attrName}（${a.attrCode}）`"
              :value="a.attrCode"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="值映射">
          <el-input
            v-model="editForm.valueMap"
            type="textarea"
            :rows="3"
            placeholder='JSON，如 {"1":"异常","0":"正常"}'
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button
          v-if="editRow?.mapping"
          type="danger"
          plain
          :loading="clearing"
          @click="clearMapping"
        >清除映射</el-button>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!editForm.conceptCode || !editForm.attrCode"
          @click="saveEdit"
        >保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增数据源 -->
    <el-dialog v-model="createVisible" title="新增数据源" width="520px">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="90px">
        <el-form-item label="编码" prop="dsCode">
          <el-input v-model="createForm.dsCode" placeholder="如 DS_BLOOD（建议 DS_ 前缀大写）" />
        </el-form-item>
        <el-form-item label="名称" prop="dsName">
          <el-input v-model="createForm.dsName" placeholder="如 血库系统库" />
        </el-form-item>
        <el-form-item label="产品线">
          <el-input v-model="createForm.productName" placeholder="可选，如 血库系统" />
        </el-form-item>
        <el-form-item label="库类型">
          <el-select v-model="createForm.dbType" disabled style="width: 100%">
            <el-option label="MySQL" value="MYSQL" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机" prop="host">
          <el-input v-model="createForm.host" placeholder="127.0.0.1" />
        </el-form-item>
        <el-form-item label="端口" prop="port">
          <el-input-number
            v-model="createForm.port"
            :min="1"
            :max="65535"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="数据库名" prop="dbName">
          <el-input v-model="createForm.dbName" placeholder="如 demo_blood" />
        </el-form-item>
        <el-form-item label="账号" prop="username">
          <el-input v-model="createForm.username" placeholder="只读账号即可" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="createForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :loading="testing" @click="doTest">测试连接</el-button>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">注册</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox, ElLoading } from 'element-plus'
import {
  listDatasources,
  scanDatasource,
  createDatasource,
  testDatasource,
  updateDatasourceStatus,
  deleteDatasource,
  listTables,
  listColumns,
  listMappings,
  saveMappings,
  aiSuggest,
  deleteMapping,
  startOntologyAnalysis,
  latestOntologyAnalysis,
  getOntologyChangeSet,
  updateOntologyChangeItem,
  adoptOntologyChangeItems,
  publishOntologyChangeSet
} from '../../api/datasource'
import { conceptDetail } from '../../api/ontology'
import { useConceptStore } from '../../store/concept'
import { useUserStore } from '../../store/user'

const conceptStore = useConceptStore()
const userStore = useUserStore()

// ---------- 数据源 ----------
const datasources = ref([])
const loadingDs = ref(false)
const currentDs = ref(null)
const scanningDs = ref('')
const togglingDs = ref('')
const deletingDs = ref('')

const isDisabled = (ds) => ds?.status === 'DISABLED'

const loadDatasources = async () => {
  loadingDs.value = true
  try {
    datasources.value = await listDatasources()
  } finally {
    loadingDs.value = false
  }
}

const selectDs = (ds) => {
  currentDs.value = ds
  clearWorkbench()
  // 失效数据源不参与业务流程，后端已拦截表/列读取，这里不再发起请求
  if (!isDisabled(ds)) loadTables()
  loadAnalysis()
}

const doScan = async (ds) => {
  scanningDs.value = ds.dsCode
  try {
    const res = await scanDatasource(ds.dsCode)
    ElMessage.success(`扫描完成：${res.dsCode} 共 ${res.tableCount} 张表`)
    if (currentDs.value?.dsCode === ds.dsCode) {
      analysis.value = {
        id: res.analysisTaskId,
        status: res.analysisStatus,
        progress: 0
      }
      scheduleAnalysisPoll()
    }
    if (currentDs.value?.dsCode === ds.dsCode) {
      loadTables()
    }
  } finally {
    scanningDs.value = ''
  }
}

// ---------- 整库 AI 本体治理 ----------
const analysis = ref(null)
const analysisLoading = ref(false)
const analysisStarting = ref(false)
let analysisTimer = null

const analysisStatusText = (status) => ({
  PENDING: '等待分析', RUNNING: '分析中', SUCCEEDED: '分析完成', PARTIAL: '部分完成',
  FAILED: '分析失败', CANCELLED: '已取消'
}[status] || status || '未知')

const analysisStatusType = (status) => ({
  SUCCEEDED: 'success', PARTIAL: 'warning', FAILED: 'danger', CANCELLED: 'info', RUNNING: 'primary'
}[status] || 'info')

const stopAnalysisPoll = () => {
  if (analysisTimer) window.clearTimeout(analysisTimer)
  analysisTimer = null
}

const scheduleAnalysisPoll = () => {
  stopAnalysisPoll()
  if (analysis.value && ['PENDING', 'RUNNING'].includes(analysis.value.status)) {
    analysisTimer = window.setTimeout(async () => {
      await loadAnalysis(false)
      scheduleAnalysisPoll()
    }, 3000)
  }
}

const loadAnalysis = async (showLoading = true) => {
  if (!currentDs.value || isDisabled(currentDs.value)) {
    analysis.value = null
    stopAnalysisPoll()
    return
  }
  const dsCode = currentDs.value.dsCode
  if (showLoading) analysisLoading.value = true
  try {
    const result = await latestOntologyAnalysis(dsCode)
    if (currentDs.value?.dsCode === dsCode) {
      analysis.value = result
      scheduleAnalysisPoll()
    }
  } finally {
    if (showLoading) analysisLoading.value = false
  }
}

const restartAnalysis = async () => {
  analysisStarting.value = true
  try {
    analysis.value = await startOntologyAnalysis(currentDs.value.dsCode, { force: true })
    ElMessage.success('已创建新的治理分析任务')
    scheduleAnalysisPoll()
  } finally {
    analysisStarting.value = false
  }
}

const governanceVisible = ref(false)
const changeSet = ref(null)
const changeLoading = ref(false)
const changeSaving = ref(false)
const changePublishing = ref(false)
const selectedChangeItems = ref([])
const changeTableRef = ref(null)
const changeFilters = reactive({ type: '', risk: '', status: '', table: '', confidence: '' })
const changeItemTypes = ['CONCEPT', 'ATTRIBUTE', 'TERM', 'RELATION', 'RULE', 'ACTION', 'METRIC', 'MAPPING']
const changeMutable = computed(() => ['DRAFT', 'REVIEWED', 'ADOPTED'].includes(changeSet.value?.status))
const acceptedChangeCount = computed(() => (changeSet.value?.items || []).filter((item) => item.reviewStatus === 'ACCEPTED').length)

const filteredChangeItems = computed(() => (changeSet.value?.items || []).filter((item) =>
  (!changeFilters.type || item.itemType === changeFilters.type) &&
  (!changeFilters.risk || item.riskLevel === changeFilters.risk) &&
  (!changeFilters.status || item.reviewStatus === changeFilters.status) &&
  (!changeFilters.confidence || (item.confidence || 0) >= changeFilters.confidence) &&
  (!changeFilters.table || (item.sourceTable || '').toLowerCase().includes(changeFilters.table.toLowerCase()))
))

const riskTag = (risk) => ({ HIGH: 'danger', MEDIUM: 'warning', LOW: 'success' }[risk] || 'info')
const selectableChangeItem = (item) =>
  changeMutable.value && !['CONFLICT', 'INSUFFICIENT_EVIDENCE'].includes(item.operation)
const onChangeSelection = (rows) => { selectedChangeItems.value = rows }

const openGovernanceWorkbench = async () => {
  governanceVisible.value = true
  changeLoading.value = true
  try {
    changeSet.value = await getOntologyChangeSet(analysis.value.changeSet.id)
  } finally {
    changeLoading.value = false
  }
}

const reloadChangeSet = async () => {
  if (!changeSet.value?.id) return
  changeSet.value = await getOntologyChangeSet(changeSet.value.id)
  selectedChangeItems.value = []
}

const reviewChangeItem = async (item, reviewStatus) => {
  changeSaving.value = true
  try {
    await updateOntologyChangeItem(changeSet.value.id, item.id, { reviewStatus })
    await reloadChangeSet()
  } finally {
    changeSaving.value = false
  }
}

const changeEditVisible = ref(false)
const editingChangeItem = ref(null)
const changePayloadText = ref('')
const changeReviewNote = ref('')

const editChangeItem = (item) => {
  editingChangeItem.value = item
  changePayloadText.value = JSON.stringify(item.payload || {}, null, 2)
  changeReviewNote.value = item.reviewNote || ''
  changeEditVisible.value = true
}

const saveChangeEdit = async () => {
  let payload
  try {
    payload = JSON.parse(changePayloadText.value)
  } catch {
    ElMessage.error('载荷 JSON 格式不正确')
    return
  }
  changeSaving.value = true
  try {
    await updateOntologyChangeItem(changeSet.value.id, editingChangeItem.value.id, {
      payload,
      reviewNote: changeReviewNote.value
    })
    changeEditVisible.value = false
    await reloadChangeSet()
    ElMessage.success('建议已更新')
  } finally {
    changeSaving.value = false
  }
}

const adoptSelectedChanges = async () => {
  changeSaving.value = true
  try {
    const result = await adoptOntologyChangeItems(changeSet.value.id, selectedChangeItems.value.map((item) => item.id))
    await reloadChangeSet()
    ElMessage.success(`已采纳 ${result.acceptedCount} 项建议（含依赖）`)
  } finally {
    changeSaving.value = false
  }
}

const publishChanges = async () => {
  await ElMessageBox.confirm(
    '将已采纳建议原子化创建为本体草稿与未确认候选映射，仍需走现有审核发布流程。确认继续？',
    '发布变更集',
    { type: 'warning' }
  )
  changePublishing.value = true
  try {
    const result = await publishOntologyChangeSet(changeSet.value.id)
    ElMessage.success(`变更集已发布，共创建 ${result.created?.length || 0} 项`)
    await reloadChangeSet()
    await conceptStore.fetchAll()
    await loadAnalysis()
  } finally {
    changePublishing.value = false
  }
}

const toggleStatus = async (ds) => {
  togglingDs.value = ds.dsCode
  try {
    const target = isDisabled(ds) ? 'ACTIVE' : 'DISABLED'
    const updated = await updateDatasourceStatus(ds.dsCode, target)
    ElMessage.success(target === 'DISABLED' ? `已失效：${updated.dsName}` : `已激活：${updated.dsName}`)
    await loadDatasources()
    if (currentDs.value?.dsCode === ds.dsCode) {
      const fresh = datasources.value.find((d) => d.dsCode === ds.dsCode)
      currentDs.value = fresh || null
      clearWorkbench()
      if (fresh && !isDisabled(fresh)) loadTables()
    }
  } finally {
    togglingDs.value = ''
  }
}

const doDelete = (ds) => {
  ElMessageBox.confirm(
    `删除后「${ds.dsName}」将不再展示，且不能参与扫描、映射、问数等业务流程；历史映射与扫描快照保留。`,
    '删除数据源',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
    .then(async () => {
      deletingDs.value = ds.dsCode
      try {
        await deleteDatasource(ds.dsCode)
        ElMessage.success(`已删除：${ds.dsName}`)
        if (currentDs.value?.dsCode === ds.dsCode) {
          currentDs.value = null
          clearWorkbench()
        }
        await loadDatasources()
      } finally {
        deletingDs.value = ''
      }
    })
    .catch(() => {})
}

// ---------- 新增数据源 ----------
const createVisible = ref(false)
const createFormRef = ref(null)
const testing = ref(false)
const creating = ref(false)
const createForm = reactive({
  dsCode: '',
  dsName: '',
  productName: '',
  dbType: 'MYSQL',
  host: '127.0.0.1',
  port: 3306,
  dbName: '',
  username: '',
  password: ''
})
const createRules = {
  dsCode: [{ required: true, message: '请输入数据源编码', trigger: 'blur' }],
  dsName: [{ required: true, message: '请输入数据源名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入主机地址', trigger: 'blur' }],
  dbName: [{ required: true, message: '请输入数据库名', trigger: 'blur' }],
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const openCreate = () => {
  Object.assign(createForm, {
    dsCode: '',
    dsName: '',
    productName: '',
    dbType: 'MYSQL',
    host: '127.0.0.1',
    port: 3306,
    dbName: '',
    username: '',
    password: ''
  })
  createVisible.value = true
  nextTick(() => createFormRef.value?.clearValidate())
}

const doTest = async () => {
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return
  testing.value = true
  try {
    const ok = await testDatasource({ ...createForm })
    if (ok) {
      ElMessage.success('连接成功')
    } else {
      ElMessage.warning('连接失败：请检查地址、端口、数据库名、账号或密码')
    }
  } finally {
    testing.value = false
  }
}

const doCreate = async () => {
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return
  if (datasources.value.some((d) => d.dsCode === createForm.dsCode)) {
    ElMessage.warning(`数据源编码已存在：${createForm.dsCode}`)
    return
  }
  creating.value = true
  try {
    const ds = await createDatasource({ ...createForm })
    ElMessage.success(`数据源注册成功：${ds.dsName}`)
    createVisible.value = false
    await loadDatasources()
    const created = datasources.value.find((d) => d.dsCode === ds.dsCode)
    if (created) {
      selectDs(created)
      doScan(created).catch(() => {})
    }
  } finally {
    creating.value = false
  }
}

// ---------- 物理表 ----------
const tables = ref([])
const loadingTables = ref(false)
const currentTable = ref('')

// 清空右侧表/列/映射工作区（切换失效、删除数据源时调用）
const clearWorkbench = () => {
  tables.value = []
  currentTable.value = ''
  columns.value = []
  mappings.value = []
  suggestions.value = {}
  accepted.value = new Set()
  aiMeta.value = null
}

const loadTables = async () => {
  if (!currentDs.value) return
  loadingTables.value = true
  try {
    tables.value = await listTables(currentDs.value.dsCode)
  } finally {
    loadingTables.value = false
  }
}

const selectTable = (row) => {
  currentTable.value = row.tableName
  aiMeta.value = null
  suggestions.value = {}
  loadWorkbench()
}

// ---------- 映射工作台 ----------
const columns = ref([])
const mappings = ref([])
const suggestions = ref({})
const accepted = ref(new Set())
const loadingColumns = ref(false)
const aiLoading = ref(false)
const aiMeta = ref(null)
const saving = ref(false)

const rows = computed(() =>
  columns.value.map((col) => ({
    ...col,
    mapping: mappings.value.find((m) => m.columnName === col.columnName) || null,
    suggestion: suggestions.value[col.columnName] || null,
    accepted: accepted.value.has(col.columnName)
  }))
)

const acceptedRows = computed(() => rows.value.filter((r) => r.accepted && r.suggestion))

const loadWorkbench = async () => {
  if (!currentDs.value || !currentTable.value) return
  loadingColumns.value = true
  try {
    const [cols, maps] = await Promise.all([
      listColumns(currentDs.value.dsCode, currentTable.value),
      listMappings(currentDs.value.dsCode, currentTable.value)
    ])
    columns.value = cols
    mappings.value = maps
    accepted.value = new Set()
  } finally {
    loadingColumns.value = false
  }
}

// ---------- AI 推荐 ----------
const runAiSuggest = async () => {
  aiLoading.value = true
  const loadingInstance = ElLoading.service({
    text: 'deepseek-v4-flash 推理中，请稍候…',
    background: 'rgba(255, 255, 255, 0.7)'
  })
  try {
    const res = await aiSuggest(currentDs.value.dsCode, currentTable.value)
    aiMeta.value = { llmUsed: res.llmUsed, model: res.model }
    const map = {}
    for (const s of res.suggestions || []) {
      map[s.column] = s
    }
    suggestions.value = map
    accepted.value = new Set()
    ElMessage.success(
      res.llmUsed ? `AI 推荐完成，共 ${res.suggestions?.length || 0} 条建议` : 'LLM 不可用，已按规则降级推荐'
    )
  } finally {
    loadingInstance.close()
    aiLoading.value = false
  }
}

const accept = (row) => {
  accepted.value = new Set([...accepted.value, row.columnName])
}

const saveAccepted = async () => {
  saving.value = true
  try {
    const payload = acceptedRows.value.map((r) => ({
      dsCode: currentDs.value.dsCode,
      tableName: currentTable.value,
      columnName: r.columnName,
      conceptCode: r.suggestion.conceptCode,
      attrCode: r.suggestion.attrCode,
      confirmed: 1,
      source: 'AI'
    }))
    await saveMappings(payload)
    ElMessage.success(`已保存 ${payload.length} 条映射`)
    suggestions.value = {}
    aiMeta.value = null
    loadWorkbench()
  } finally {
    saving.value = false
  }
}

// ---------- 手动编辑映射 ----------
const editVisible = ref(false)
const editRow = ref(null)
const editForm = reactive({ conceptCode: '', attrCode: '', valueMap: '' })
const attrOptions = ref([])
const clearing = ref(false)

const onConceptChange = async (code) => {
  editForm.attrCode = ''
  attrOptions.value = []
  if (!code) return
  const detail = await conceptDetail(code)
  attrOptions.value = detail.attributes || []
}

const openEdit = async (row) => {
  editRow.value = row
  editForm.conceptCode = row.mapping?.conceptCode || ''
  editForm.attrCode = row.mapping?.attrCode || ''
  editForm.valueMap = row.mapping?.valueMap || ''
  attrOptions.value = []
  editVisible.value = true
  if (editForm.conceptCode) {
    const detail = await conceptDetail(editForm.conceptCode)
    attrOptions.value = detail.attributes || []
  }
}

const saveEdit = async () => {
  saving.value = true
  try {
    await saveMappings([
      {
        dsCode: currentDs.value.dsCode,
        tableName: currentTable.value,
        columnName: editRow.value.columnName,
        conceptCode: editForm.conceptCode,
        attrCode: editForm.attrCode,
        valueMap: editForm.valueMap?.trim() || null,
        confirmed: 1,
        source: 'MANUAL'
      }
    ])
    ElMessage.success('映射已保存')
    editVisible.value = false
    loadWorkbench()
  } finally {
    saving.value = false
  }
}

const clearMapping = async () => {
  clearing.value = true
  try {
    await deleteMapping(editRow.value.mapping.id)
    ElMessage.success('映射已清除')
    editVisible.value = false
    loadWorkbench()
  } finally {
    clearing.value = false
  }
}

onMounted(() => {
  loadDatasources()
  conceptStore.fetchAll()
})

onUnmounted(stopAnalysisPoll)
</script>

<style scoped>
.ds-cards {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.ds-card {
  width: 260px;
  cursor: pointer;
  border: 1px solid #e4e7ed;
  position: relative;
}

.ds-card.active {
  border-color: #409eff;
  box-shadow: 0 0 0 1px #409eff inset;
}

.ds-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 8px;
}

.ds-meta {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.ds-card.disabled {
  background: #f5f7fa;
}

.ds-card.disabled .ds-title,
.ds-card.disabled .ds-meta {
  color: #c0c4cc;
}

.ds-actions {
  margin-top: 8px;
}

.add-card {
  border: 1px dashed #c0c4cc;
  cursor: pointer;
}

.add-card:hover {
  border-color: #409eff;
}

.add-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 104px;
  color: #909399;
}

.add-card:hover .add-inner {
  color: #409eff;
}

.add-plus {
  font-size: 28px;
  line-height: 1;
  margin-bottom: 8px;
  font-weight: 300;
}

.footer-bar {
  margin-top: 12px;
  text-align: right;
}

.no-suggest {
  color: #c0c4cc;
}

.card-header,
.analysis-summary,
.analysis-actions,
.change-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-header,
.analysis-actions {
  justify-content: space-between;
}

.analysis-summary {
  flex-wrap: wrap;
  color: #606266;
  font-size: 13px;
}

.analysis-actions {
  margin-top: 12px;
  color: #606266;
}

.change-toolbar {
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.change-state {
  margin-left: auto;
  color: #606266;
}

.evidence-panel {
  padding: 4px 24px 12px;
  color: #606266;
}

.evidence-panel pre {
  max-height: 240px;
  overflow: auto;
  padding: 12px;
  border-radius: 4px;
  background: #f5f7fa;
}
</style>
