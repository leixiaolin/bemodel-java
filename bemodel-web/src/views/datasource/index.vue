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
                      v-if="row.mapping.source === 'AI'"
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
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
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
  deleteMapping
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
}

const doScan = async (ds) => {
  scanningDs.value = ds.dsCode
  try {
    const res = await scanDatasource(ds.dsCode)
    ElMessage.success(`扫描完成：${res.dsCode} 共 ${res.tableCount} 张表`)
    if (currentDs.value?.dsCode === ds.dsCode) {
      loadTables()
    }
  } finally {
    scanningDs.value = ''
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
</style>
