import React from 'react';
import { ReviewDecisionDialog } from './ReviewDecisionDialog';
import type { ReviewDecisionText } from './ReviewDecisionDialog';

export type MetricDecision = 'candidate' | 'approve' | 'revoke';

const DECISION_TEXT: Record<MetricDecision, ReviewDecisionText> = {
  candidate: {
    title: 'Tạo bản đề xuất',
    description: 'Công thức hiện tại được lưu lại và chuyển sang trạng thái chờ duyệt.',
    reasonLabel: 'Ghi chú cho người duyệt (không bắt buộc)',
    confirmLabel: 'Gửi đề xuất',
    reasonRequired: false,
  },
  approve: {
    title: 'Duyệt metric',
    description: 'Sau khi duyệt, AI Agent và người dùng có quyền trên dataset có thể truy vấn metric này.',
    reasonLabel: 'Ghi chú khi duyệt (không bắt buộc)',
    confirmLabel: 'Duyệt',
    reasonRequired: false,
  },
  revoke: {
    title: 'Thu hồi metric',
    description: 'Metric sẽ không chạy được nữa cho tới khi được đề xuất và duyệt lại.',
    reasonLabel: 'Lý do thu hồi (bắt buộc)',
    confirmLabel: 'Thu hồi',
    reasonRequired: true,
    destructive: true,
  },
};

type MetricDecisionDialogProps = {
  decision: MetricDecision | null;
  metricLabel: string;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
};

export function MetricDecisionDialog({ decision, metricLabel, busy, onConfirm, onClose }: MetricDecisionDialogProps) {
  return (
    <ReviewDecisionDialog
      text={decision === null ? null : DECISION_TEXT[decision]}
      subject={metricLabel}
      reasonMaxLength={2000}
      busy={busy}
      onConfirm={onConfirm}
      onClose={onClose}
    />
  );
}
