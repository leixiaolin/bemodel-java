# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.
# 注意：中文注释为手工补充，重新生成本文件前请先保留注释。
# 本体（ontology）模块 ORM 实体：领域、概念、属性、关系、指标、术语及其派生表。
from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue
from bemodel.core.database import Base


class Attribute(Base):
    """概念属性表（bm_attribute）。

    描述概念下的原子字段（如"患者.性别"、"订单.金额"），
    是实例层语义映射（属性 -> 物理表列）的锚点。
    """

    __tablename__ = 'bm_attribute'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 所属概念编码，关联 bm_concept.code
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    # 属性编码，概念内唯一
    attr_code = Column('attr_code', Text, nullable=True, server_default=FetchedValue())
    # 属性中文名称
    attr_name = Column('attr_name', Text, nullable=True, server_default=FetchedValue())
    # 数据类型（STRING / INT / DATE 等）
    data_type = Column('data_type', Text, nullable=True, server_default=FetchedValue())
    # 是否关键属性：1 是，0 否
    is_key = Column('is_key', Integer, nullable=True, server_default=FetchedValue())
    # 业务定义 / 口径说明
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    # 显示排序号
    sort = Column('sort', Integer, nullable=True, server_default=FetchedValue())


class Concept(Base):
    """概念表（bm_concept）。

    业务本体中的核心实体（如"患者"、"药品"、"收费项"），
    支持版本、状态与 IRI 标识以便导出 RDF/OWL。
    """

    __tablename__ = 'bm_concept'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 概念编码，全局唯一
    code = Column('code', Text, nullable=True, server_default=FetchedValue())
    # 概念中文名称
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    # 所属领域编码，关联 bm_domain.code
    domain_code = Column('domain_code', Text, nullable=True, server_default=FetchedValue())
    # 概念定义说明
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    # 责任人
    owner = Column('owner', Text, nullable=True, server_default=FetchedValue())
    # 状态（草稿 / 已发布等）
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    # 版本号，发布时递增
    version = Column('version', Integer, nullable=True, server_default=FetchedValue())
    # RDF/OWL 中的实体 IRI
    iri = Column('iri', Text, nullable=True, server_default=FetchedValue())
    # 创建时间
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    # 更新时间
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class ConceptParent(Base):
    """概念父子（继承）关系表（bm_concept_parent）。

    记录概念之间的上下位层级，支持多父继承，
    其中 is_primary 标记主继承轴。
    """

    __tablename__ = 'bm_concept_parent'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 子概念编码
    child_code = Column('child_code', Text, nullable=True, server_default=FetchedValue())
    # 父概念编码
    parent_code = Column('parent_code', Text, nullable=True, server_default=FetchedValue())
    # 是否主父概念：1 是，0 否
    is_primary = Column('is_primary', Integer, nullable=True, server_default=FetchedValue())
    # 创建时间
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class Disjoint(Base):
    """概念互斥（不相交）公理表（bm_concept_disjoint）。

    声明两个概念在语义上不可能同时成立，
    用于 SHACL / OWL 校验时发现建模冲突。
    """

    __tablename__ = 'bm_concept_disjoint'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 概念 A 编码
    concept_a_code = Column('concept_a_code', Text, nullable=True, server_default=FetchedValue())
    # 概念 B 编码
    concept_b_code = Column('concept_b_code', Text, nullable=True, server_default=FetchedValue())
    # 互斥关系说明
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    # 状态（生效 / 停用等）
    status = Column('status', Text, nullable=True, server_default=FetchedValue())
    # 创建时间
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    # 更新时间
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class Domain(Base):
    """业务领域（主题域）表（bm_domain）。

    本体的顶层分组，如"医疗域"、"结算域"，
    概念通过 domain_code 归属到领域。
    """

    __tablename__ = 'bm_domain'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 领域编码，全局唯一
    code = Column('code', Text, nullable=True, server_default=FetchedValue())
    # 领域中文名称
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    # 领域描述说明
    description = Column('description', Text, nullable=True, server_default=FetchedValue())
    # 显示排序号
    sort = Column('sort', Integer, nullable=True, server_default=FetchedValue())
    # 创建时间
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())
    # 更新时间
    updated_at = Column('updated_at', DateTime, nullable=True, server_default=FetchedValue())


class Metric(Base):
    """指标表（bm_metric）。

    定义业务指标的业务口径与计算公式，
    并可通过探测 SQL 定期巡检取数、按阈值告警。
    """

    __tablename__ = 'bm_metric'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 指标编码，全局唯一
    metric_code = Column('metric_code', Text, nullable=True, server_default=FetchedValue())
    # 指标中文名称
    name = Column('name', Text, nullable=True, server_default=FetchedValue())
    # 业务口径定义
    definition = Column('definition', Text, nullable=True, server_default=FetchedValue())
    # 计算公式 / 表达式
    formula = Column('formula', Text, nullable=True, server_default=FetchedValue())
    # 所属概念编码，关联 bm_concept.code
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    # 责任人
    owner = Column('owner', Text, nullable=True, server_default=FetchedValue())
    # 关联数据源编码（探测 SQL 执行的目标库）
    ds_code = Column('ds_code', Text, nullable=True, server_default=FetchedValue())
    # 探测 SQL，巡检时执行取数
    probe_sql = Column('probe_sql', Text, nullable=True, server_default=FetchedValue())
    # 告警阈值，巡检值超过则告警
    warn_threshold = Column('warn_threshold', Integer, nullable=True, server_default=FetchedValue())
    # 最近一次巡检值
    last_val = Column('last_val', Integer, nullable=True, server_default=FetchedValue())
    # 最近一次评估时间
    last_eval_at = Column('last_eval_at', DateTime, nullable=True, server_default=FetchedValue())
    # 创建时间
    created_at = Column('created_at', DateTime, nullable=True, server_default=FetchedValue())


class OntologyMiss(Base):
    """本体缺失词表（bm_ontology_miss）。

    记录问数 / 搜索等场景中未能命中本体的术语，
    支持忽略、采纳为本体概念/属性、以及撤销采纳，形成本体进化闭环。
    """

    __tablename__ = 'bm_ontology_miss'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 未命中的术语原文
    term = Column('term', Text, nullable=True, server_default=FetchedValue())
    # 类型（概念 / 属性等）
    kind = Column('kind', Text, nullable=True, server_default=FetchedValue())
    # 发现来源（问数、客服、搜索等场景）
    source = Column('source', Text, nullable=True, server_default=FetchedValue())
    # 累计出现次数
    count = Column('count', Integer, nullable=True, server_default=FetchedValue())
    # 是否已忽略：1 是，0 否
    dismissed = Column('dismissed', Integer, nullable=True, server_default=FetchedValue())
    # 忽略原因说明
    dismiss_reason = Column('dismiss_reason', Text, nullable=True, server_default=FetchedValue())
    # 采纳后挂接的概念编码
    adopted_concept_code = Column('adopted_concept_code', Text, nullable=True, server_default=FetchedValue())
    # 采纳方式（作为新概念 / 属性 / 同义词等）
    adopted_as = Column('adopted_as', Text, nullable=True, server_default=FetchedValue())
    # 是否已撤销采纳：1 是，0 否
    revoked = Column('revoked', Integer, nullable=True, server_default=FetchedValue())
    # 首次发现时间
    first_seen = Column('first_seen', DateTime, nullable=True, server_default=FetchedValue())
    # 最近发现时间
    last_seen = Column('last_seen', DateTime, nullable=True, server_default=FetchedValue())


class Relation(Base):
    """概念间关系表（bm_relation）。

    定义概念之间的语义关系（如"包含"、"治疗"），
    携带对称/传递/函数性等公理标记与逆关系，用于推理与图遍历。
    """

    __tablename__ = 'bm_relation'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 起点概念编码
    from_concept = Column('from_concept', Text, nullable=True, server_default=FetchedValue())
    # 终点概念编码
    to_concept = Column('to_concept', Text, nullable=True, server_default=FetchedValue())
    # 关系名称（如包含 / 治疗 / 引用）
    relation_name = Column('relation_name', Text, nullable=True, server_default=FetchedValue())
    # 关系说明
    description = Column('description', Text, nullable=True, server_default=FetchedValue())
    # 是否对称：1 是，0 否
    is_symmetric = Column('is_symmetric', Integer, nullable=True, server_default=FetchedValue())
    # 是否传递：1 是，0 否
    is_transitive = Column('is_transitive', Integer, nullable=True, server_default=FetchedValue())
    # 是否函数性（每个主体至多一个客体）：1 是，0 否
    is_functional = Column('is_functional', Integer, nullable=True, server_default=FetchedValue())
    # 是否逆函数性：1 是，0 否
    is_inverse_functional = Column('is_inverse_functional', Integer, nullable=True, server_default=FetchedValue())
    # 是否非对称：1 是，0 否
    is_asymmetric = Column('is_asymmetric', Integer, nullable=True, server_default=FetchedValue())
    # 逆关系名称（互为 inverseOf）
    inverse_of = Column('inverse_of', Text, nullable=True, server_default=FetchedValue())
    # RDF 中的谓词 IRI
    iri = Column('iri', Text, nullable=True, server_default=FetchedValue())


class RelationClosure(Base):
    """关系传递闭包表（bm_relation_closure）。

    物化关系的多跳可达路径（A -> ... -> C, depth=N），
    加速影响分析、血缘追溯等图遍历查询，避免递归计算。
    """

    __tablename__ = 'bm_relation_closure'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 关系名称
    relation_name = Column('relation_name', Text, nullable=True, server_default=FetchedValue())
    # 起点概念编码
    from_concept = Column('from_concept', Text, nullable=True, server_default=FetchedValue())
    # 终点概念编码
    to_concept = Column('to_concept', Text, nullable=True, server_default=FetchedValue())
    # 跳数（路径深度）
    depth = Column('depth', Integer, nullable=True, server_default=FetchedValue())


class Term(Base):
    """业务术语表（bm_term）。

    记录各业务系统/产品对概念的叫法（同义词、缩写、标准编码），
    供语义搜索与问数做术语归一。
    """

    __tablename__ = 'bm_term'
    # 主键
    id = Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    # 术语文本（同义词 / 缩写等）
    term = Column('term', Text, nullable=True, server_default=FetchedValue())
    # 挂接的概念编码，关联 bm_concept.code
    concept_code = Column('concept_code', Text, nullable=True, server_default=FetchedValue())
    # 来源产品 / 业务系统
    source_product = Column('source_product', Text, nullable=True, server_default=FetchedValue())
    # 术语类型（同义词 / 缩写等）
    term_type = Column('term_type', Text, nullable=True, server_default=FetchedValue())
    # 编码体系（如 ICD、LOINC 等标准字典）
    code_system = Column('code_system', Text, nullable=True, server_default=FetchedValue())
    # 对应的标准编码
    standard_code = Column('standard_code', Text, nullable=True, server_default=FetchedValue())
