import type { ExpertRuleCondition, ExpertRuleConditionValue, ExpertRuleOperator } from './types';

export const OPERATOR_LABELS: Record<ExpertRuleOperator, string> = {
  equals: 'bằng',
  not_equals: 'khác',
  contains: 'chứa',
  not_contains: 'không chứa',
  greater_than: 'lớn hơn',
  greater_than_or_equal: 'lớn hơn hoặc bằng',
  less_than: 'nhỏ hơn',
  less_than_or_equal: 'nhỏ hơn hoặc bằng',
  in: 'thuộc',
  not_in: 'không thuộc',
  is_null: 'để trống',
  is_not_null: 'có giá trị',
};

export const VALUELESS_OPERATORS: ExpertRuleOperator[] = ['is_null', 'is_not_null'];
export const LIST_OPERATORS: ExpertRuleOperator[] = ['in', 'not_in'];

export type ColumnValueKind = 'number' | 'boolean' | 'string';

export function columnValueKind(dataType: string | undefined): ColumnValueKind {
  const normalized = (dataType ?? '').toUpperCase();
  if (/BOOL/.test(normalized)) return 'boolean';
  if (/INT|FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|NUMBER/.test(normalized)) return 'number';
  return 'string';
}

export function formatConditionValue(value: ExpertRuleConditionValue): string {
  if (Array.isArray(value)) return value.map(item => String(item)).join(', ');
  if (value === null) return '';
  if (typeof value === 'boolean') return value ? 'đúng' : 'sai';
  return String(value);
}

/** Reads a condition as a phrase such as "Nhiệt độ tối đa lớn hơn hoặc bằng 35". */
export function conditionPhrase(condition: ExpertRuleCondition, columnName: string): string {
  const operator = OPERATOR_LABELS[condition.operator];
  if (VALUELESS_OPERATORS.includes(condition.operator)) return `${columnName} ${operator}`;
  return `${columnName} ${operator} ${formatConditionValue(condition.value)}`;
}

const FIELD_LABELS: Record<string, string> = {
  name: 'tên rule',
  conditions: 'điều kiện',
  'conditions.operator': 'phép so sánh',
  exceptions: 'ngoại lệ',
  'exceptions.when': 'ngoại lệ (khi)',
  'exceptions.outcome': 'ngoại lệ (thì)',
  examples: 'câu hỏi mẫu',
  'examples.question': 'câu hỏi mẫu',
  'examples.intent': 'cách hiểu câu hỏi',
  reason: 'lý do',
};

/** Turns the backend's English validation messages into Vietnamese the reviewer can act on. */
export function expertRuleErrorMessage(message: string): string {
  const unsafe = message.match(/^Unsafe (.+)\.$/);
  if (unsafe) {
    const field = FIELD_LABELS[unsafe[1]] ?? unsafe[1];
    return `Nội dung ${field} chỉ được là mô tả, không chứa câu lệnh SQL, đường dẫn hay thông tin bí mật.`;
  }
  if (message === 'Invalid metric link.') return 'Metric liên kết không còn ở trạng thái đã duyệt.';
  if (message === 'Invalid glossary link.') return 'Thuật ngữ liên kết không còn ở trạng thái đã duyệt.';
  if (message.includes('at least one approved glossary term')) return 'Rule cần ít nhất một thuật ngữ đã duyệt.';
  if (message.includes('already exists')) return 'Đã có rule cùng tên.';
  if (message.includes('changed; refresh')) return 'Rule vừa được người khác thay đổi; tải lại rồi thử lại.';
  const invalid = message.match(/^(?:Invalid|Duplicate) (.+)\.$/);
  if (invalid) return `Kiểm tra lại ${FIELD_LABELS[invalid[1]] ?? invalid[1]}.`;
  return message;
}
