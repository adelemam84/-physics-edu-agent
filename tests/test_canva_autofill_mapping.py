from app.external_creative_integrations import _semantic_canva_values


def test_canva_master_mapping_is_source_grounded_and_sparse():
    summary = {
        'title': 'الحركة في خط مستقيم',
        'subject': 'physics',
        'grade_label': 'الصف الأول الثانوي',
        'summary': 'ملخص من المصدر فقط',
        'sections': [
            {'title': 'المسافة والإزاحة', 'summary': 'تعريفات المصدر', 'source_refs': ['ص1']},
            {'title': 'السرعة', 'summary': 'شرح السرعة من المصدر', 'source_refs': ['ص2']},
            {'title': 'التسارع', 'summary': 'شرح التسارع من المصدر', 'source_refs': ['ص3']},
        ],
        'equations': [
            {'label': 'السرعة', 'expression': 'v = d / t', 'notes': 'كما ورد بالمصدر'}
        ],
        'diagrams': [
            {'title': 'رسم الحركة', 'description': 'وصف المصدر', 'labels': ['موضع 1', 'موضع 2']}
        ],
    }

    values = _semantic_canva_values(summary)

    assert values['LESSON_TITLE'] == summary['title']
    assert values['MINDMAP_BRANCH_1_TITLE'] == 'المسافة والإزاحة'
    assert 'v = d / t' in values['EQUATIONS_BODY']
    assert values['FIGURE_TITLE'] == 'رسم الحركة'
    assert values['EXAMPLE_PROBLEM'] == ''
    assert values['COMMON_MISTAKE'] == ''
    assert values['TITLE'] == summary['title']
    assert values['SECTION_1_SOURCE'] == 'ص1'


def test_canva_master_mapping_handles_minimal_summary_without_invention():
    values = _semantic_canva_values({
        'title': 'درس',
        'subject': 'science',
        'grade_label': '',
        'summary': '',
        'sections': [],
        'equations': [],
        'diagrams': [],
    })

    assert values['LESSON_TITLE'] == 'درس'
    assert values['OVERVIEW_BODY'] == ''
    assert values['COMPARISON_TITLE'] == ''
    assert values['EQUATIONS_TITLE'] == ''
    assert values['FIGURE_CALLOUT_1'] == ''
    assert values['EXAM_TIP'] == ''
