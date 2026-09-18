import request from './request'

// ---------- 数据源 ----------
export const listDatasources = () => request.get('/datasource/list')

// body: { dsCode, dsName, productName, dbType, host, port, dbName, username, password }
// 密码落库前由后端 AES-GCM 加密；返回体密码为 **** 掩码
export const createDatasource = (data) => request.post('/datasource', data)

// 连接测试（SELECT 1），返回 true/false，不落库
export const testDatasource = (data) => request.post('/datasource/test', data)

export const scanDatasource = (dsCode) => request.post(`/datasource/scan/${dsCode}`)

export const listTables = (dsCode) => request.get(`/datasource/tables/${dsCode}`)

export const listColumns = (dsCode, tableName) =>
  request.get(`/datasource/columns/${dsCode}`, { params: { tableName } })

// ---------- 映射 ----------
export const listMappings = (dsCode, tableName) =>
  request.get('/mapping/list', { params: { dsCode, tableName } })

export const saveMappings = (mappings) => request.post('/mapping/batch', mappings)

export const aiSuggest = (dsCode, tableName) =>
  request.get('/mapping/ai-suggest', { params: { dsCode, tableName } })

export const deleteMapping = (id) => request.delete(`/mapping/${id}`)
