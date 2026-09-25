-- Python 端新增（Java 后端已冻结）：LLM 审计补充模型输出摘要，便于排查同一问题答案抖动
ALTER TABLE bm_llm_log ADD COLUMN response_digest VARCHAR(512) COMMENT '模型输出摘要（截断512）';

-- 历史数据修复：映射值映射曾以裸字典文本入库（页面/注释原样保存），规范为 JSON 后枚举归一化才能生效
UPDATE bm_mapping SET value_map = '{"0":"在检","1":"完成","2":"作废"}' WHERE value_map = '0在检 1完成 2作废';
UPDATE bm_mapping SET value_map = '{"0":"正常","1":"异常"}' WHERE value_map = '0正常 1异常';
