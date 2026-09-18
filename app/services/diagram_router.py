from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class DiagramRoute:
    kind: str
    confidence: float
    reason: str
    inferred: bool

    def as_dict(self) -> dict:
        return asdict(self)


ALIASES = {
    'circuit': 'simple_circuit',
    'electric_circuit': 'simple_circuit',
    'series_parallel': 'series_parallel_circuit',
    'resistor_network': 'resistor_network',
    'graph': 'graph_axes',
    'chart_axes': 'graph_axes',
    'flow': 'process',
    'tree': 'classification',
    'foodchain': 'food_chain',
    'atom': 'atom_shell',
    'ray': 'ray_diagram',
    'solenoid': 'solenoid_field',
    'molecule': 'molecule_bond',
    'chem_lab': 'chemistry_lab_setup',
    'free_body': 'force_diagram',
    'force': 'force_diagram',
    'plot': 'graph_plot',
    'particle': 'particle_model',
    'reaction_profile': 'reaction_profile',
    'cell': 'cell_structure',
    'food_web': 'food_web',
    'earth_layers': 'earth_layers',
}

_KEYWORDS = [
    ('force_diagram', ('مخطط قوى', 'قوى مؤثرة', 'قوة محصلة', 'free body', 'force diagram')),
    ('graph_plot', ('منحنى بياني', 'بيانات الرسم', 'نقاط الرسم', 'plot data', 'data graph')),
    ('particle_model', ('نموذج الجسيمات', 'جسيمات المادة', 'particle model', 'particles of matter')),
    ('reaction_profile', ('طاقة التنشيط', 'منحنى طاقة التفاعل', 'reaction energy profile', 'activation energy')),
    ('cell_structure', ('تركيب الخلية', 'أجزاء الخلية', 'cell structure', 'cell organelles')),
    ('food_web', ('شبكة غذائية', 'food web', 'علاقات غذائية')),
    ('earth_layers', ('طبقات الأرض', 'تركيب الأرض', 'earth layers', 'earth structure')),
    ('series_parallel_circuit', ('توالي وتوازي', 'دائرة مركبة', 'فروع مقاومات', 'series parallel', 'mixed resistor')),
    ('resistor_network', ('شبكة مقاومات', 'مقاومات متوازية', 'توصيل مقاومات على التوازي', 'مقاومات على التوازي', 'resistor network', 'parallel resistors')),
    ('solenoid_field', ('ملف لولبي', 'solenoid', 'مجال ملف', 'مجال داخل الملف')),
    ('magnetic_field', ('مجال مغناطيسي', 'خطوط الفيض', 'حول سلك', 'magnetic field')),
    ('chemistry_lab_setup', ('جهاز تحضير غاز', 'تجربة كيميائية', 'دورق وأنبوب', 'chemistry apparatus', 'gas preparation')),
    ('molecule_bond', ('رابطة كيميائية', 'تركيب جزيء', 'molecular bond', 'molecule structure')),
    ('cycle', ('دورة', 'دورية', 'cycle', 'دوران المراحل')),
    ('food_chain', ('سلسلة غذائية', 'شبكة غذائية', 'food chain', 'منتج ومستهلك')),
    ('atom_shell', ('تركيب الذرة', 'مستويات الطاقة', 'أغلفة إلكترونية', 'electron shell', 'atomic shell')),
    ('ray_diagram', ('عدسة', 'مرآة', 'أشعة ضوئية', 'مسار الشعاع', 'ray diagram', 'lens', 'mirror')),
    ('anatomy_block', ('تشريح', 'أجزاء الجهاز', 'أجزاء العضو', 'anatomy', 'organ parts')),
    ('simple_circuit', ('دائرة كهربائية', 'مقاومة وبطارية', 'أميتر', 'فولتميتر', 'electric circuit')),
    ('graph_axes', ('رسم بياني', 'المحور السيني', 'المحور الصادي', 'graph', 'axes')),
    ('classification', ('تصنيف', 'ينقسم إلى', 'أنواع', 'classification', 'taxonomy')),
    ('comparison', ('مقارنة', 'الفرق بين', 'compare', 'versus')),
    ('vector', ('متجه', 'اتجاه القوة', 'اتجاه السرعة', 'vector', 'direction arrow')),
    ('apparatus', ('جهاز معملي', 'تركيب الجهاز', 'experimental setup', 'apparatus')),
    ('process', ('خطوات', 'مراحل', 'يتحول إلى', 'process', 'steps')),
]


def route_diagram(kind: str, title: str = '', description: str = '', subject: str = '') -> DiagramRoute:
    raw = (kind or '').strip().lower().replace(' ', '_')
    if raw in ALIASES:
        return DiagramRoute(ALIASES[raw], 1.0, 'explicit_alias', False)
    known = {
        'simple_circuit', 'series_parallel_circuit', 'resistor_network',
        'graph_axes', 'apparatus', 'process', 'comparison', 'classification', 'vector',
        'cycle', 'food_chain', 'anatomy_block', 'atom_shell', 'ray_diagram',
        'magnetic_field', 'solenoid_field', 'molecule_bond', 'chemistry_lab_setup',
        'force_diagram', 'graph_plot', 'particle_model', 'reaction_profile',
        'cell_structure', 'food_web', 'earth_layers',
    }
    if raw in known:
        return DiagramRoute(raw, 1.0, 'explicit_kind', False)
    text = f'{title} {description} {subject}'.lower()
    matches = []
    for target, words in _KEYWORDS:
        hits = sum(1 for word in words if word.lower() in text)
        if hits:
            matches.append((hits, target))
    if matches:
        matches.sort(reverse=True)
        hits, target = matches[0]
        confidence = min(0.94, 0.68 + 0.08 * hits)
        return DiagramRoute(target, confidence, 'keyword_inference', True)
    return DiagramRoute(raw or 'other', 0.0, 'no_safe_route', True)
