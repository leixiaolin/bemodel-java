<template>
  <div class="cs-tree" v-loading="loading">
    <el-tree
      v-if="treeData.length"
      :data="treeData"
      :props="{ label: 'label', children: 'children' }"
      node-key="key"
      highlight-current
      :expand-on-click-node="false"
      :default-expanded-keys="conceptKeys"
      @node-click="onNodeClick"
    >
      <template #default="{ data }">
        <div class="cs-node" :class="{ 'is-virtual': data.virtual, 'is-orphan': data.orphan }">
          <span class="cs-node-label" :title="data.item?.targetKey || data.label">{{ data.label }}</span>
          <span v-if="data.virtual" class="cs-tag cs-tag-virtual">已有概念</span>
          <template v-if="data.item">
            <el-tag size="small" effect="plain" :type="typeTag(data.item)">{{ typeLabel(data.item) }}</el-tag>
            <el-tag
              v-if="data.item.operation !== 'CREATE'"
              size="small" effect="plain" :type="operationTag(data.item)"
            >{{ operationLabel(data.item) }}</el-tag>
            <el-tag size="small" effect="light" :type="reviewTag(data.item)">{{ reviewLabel(data.item) }}</el-tag>
            <span class="cs-confidence" :class="{ 'is-low': (data.item.confidence || 0) < 0.5 }">
              {{ Math.round((data.item.confidence || 0) * 100) }}%
            </span>
          </template>
          <span v-else-if="data.attrCount != null" class="cs-count">{{ data.attrCount }} 项</span>
        </div>
      </template>
    </el-tree>
    <el-empty v-else-if="!loading" description="当前筛选无匹配建议" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { buildGroups, buildTreeData, TYPE_META, REVIEW_META, OPERATION_META } from './hierarchy'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['locate'])

const model = computed(() => buildGroups(props.items))
const treeData = computed(() => buildTreeData(model.value))
// 默认只展开概念层，属性/映射层按需展开
const conceptKeys = computed(() => treeData.value.filter((node) => node.item || node.virtual).map((node) => node.key))

const typeLabel = (item) => TYPE_META[item.itemType]?.label || item.itemType
const typeTag = (item) => TYPE_META[item.itemType]?.tag || 'info'
const operationLabel = (item) => OPERATION_META[item.operation]?.label || item.operation
const operationTag = (item) => OPERATION_META[item.operation]?.tag || 'info'
const reviewLabel = (item) => REVIEW_META[item.reviewStatus]?.label || item.reviewStatus
const reviewTag = (item) => REVIEW_META[item.reviewStatus]?.tag || 'info'

const onNodeClick = (data) => {
  // 虚拟概念与游离组头无对应表格行，不可定位
  if (data.item) emit('locate', data.item)
}
</script>

<style scoped>
.cs-tree {
  height: 560px;
  overflow: auto;
  border: 1px solid var(--border-color, #e4e7ed);
  border-radius: 4px;
  padding: 8px 4px;
  box-sizing: border-box;
}

.cs-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 26px;
  padding-right: 8px;
}

.cs-node-label {
  font-size: 13px;
  color: var(--text-primary, #303133);
}

.is-virtual > .cs-node-label,
.is-orphan > .cs-node-label {
  color: var(--text-secondary, #909399);
}

.cs-tag-virtual {
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
  border-radius: 3px;
  color: #909399;
  background: var(--fill-color-light, #f5f7fa);
  border: 1px solid var(--border-color, #e4e7ed);
}

.cs-confidence {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}

.cs-confidence.is-low {
  color: #e6a23c;
}

.cs-count {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
</style>
