from bemodel.rdf.services import mask_name, ShaclService


def test_mask_name():
    assert [mask_name(v) for v in (None, "", "张", "张三", "张建国")] == ["*", "*", "*", "张*", "张*国"]


def test_shacl_sparql_allergy_constraint():
    result = ShaclService.validate_turtle("test", '''
    @prefix med: <http://bemodel.com/ontology/med#> .
    med:patient a med:Patient; med:hasAllergyTo med:allergen; med:hasEncounter med:enc .
    med:enc a med:Encounter; med:hasOrder med:ord .
    med:ord a med:DrugOrder; med:prescribesDrug med:drug .
    med:drug med:containsAllergen med:allergen .
    ''')
    assert result["conforms"] is False
    assert result["violationCount"] >= 1
def test_all_six_shapes_on_real_demo(mysql_session):
    from bemodel.rdf.services import RdfService, ShaclService
    rdf = RdfService(mysql_session)
    export = rdf.export_patient('ZY20260815001')
    for token in ('@prefix med:', 'a med:Patient', 'a med:InpEncounter', 'a med:DrugOrder', 'med:prescribesDrug', 'med:hasDiagnosis', 'med:icd10Code', 'a med:LabResult', 'med:isAbnormal'):
        assert token in export
    allergy = rdf.export_patient('ZY20260805006')
    assert 'med:hasAllergyTo med:Allergen_头孢' in allergy and 'med:containsAllergen med:Allergen_头孢' in allergy
    shacl = ShaclService(mysql_session)
    for patient in ('ZY20260805006', 'ZY20260728012', 'ZY20260802011'):
        result = shacl.validate_patient(patient)
        assert result['conforms'] is False and result['violationCount'] > 0
    assert shacl.validate_patient('ZY20260822007')['conforms'] is True


def test_every_shape_executes():
    result = ShaclService.validate_turtle('synthetic-six-shapes', '''
    @prefix med: <http://bemodel.com/ontology/med#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    med:patient a med:Patient; med:sex "男"; med:age 8;
        med:hasAllergyTo med:allergen; med:hasEncounter med:enc .
    med:enc a med:Encounter; med:hasOrder med:ord1,med:ord2; med:hasDiagnosis med:diag .
    med:diag med:icd10Code "N83" .
    med:ord1 a med:DrugOrder; med:prescribesDrug med:drugA;
        med:singleDose "1.00"^^xsd:decimal; med:frequency "tid" .
    med:ord2 a med:DrugOrder; med:prescribesDrug med:drugB .
    med:drugA med:containsAllergen med:allergen; med:childForbidden true;
        med:maxDailyDose "2.40"^^xsd:decimal; med:interactsWith med:drugB .
    med:prescription a med:Prescription .
    ''')
    assert result['conforms'] is False
    messages = {v['message'] for v in result['violations']}
    assert messages == {'处方违反过敏禁忌：患者对药品成分过敏', '单日剂量超过药品日最大剂量',
        '儿童禁用药品用于儿童患者', '男性患者不允许出现妊娠/妇科类诊断',
        '同一就诊存在相互作用药品联用', '处方未经药师审核不得发药', '处方必须有开立医生'}
