import React, { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';

export type MetricDecision = 'candidate' | 'approve' | 'revoke';

const DECISION_TEXT: Record<MetricDecision, {
  title: string;
  description: string;
  reasonLabel: string;
  confirmLabel: string;
  reasonRequired: boolean;
}> = {
  candidate: {
    title: 'Tạo bản đề xuất',
    description: 'Công thức hiện tại sẽ được gửi cho một quản trị viên khác duyệt; bạn không thể tự duyệt.',
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
  },
};

type MetricDecisionDialogProps = {
  decision: MetricDecision | null;
  metricLabel: string;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
};

/** Asks for the note or reason that the review history keeps with each decision. */
export function MetricDecisionDialog({ decision, metricLabel, busy, onConfirm, onClose }: MetricDecisionDialogProps) {
  const [reason, setReason] = useState('');
  useEffect(() => setReason(''), [decision]);
  if (decision === null) return null;
  const text = DECISION_TEXT[decision];
  const missingReason = text.reasonRequired && !reason.trim();

  return (
    <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{text.title}: {metricLabel}</DialogTitle>
          <DialogDescription>{text.description}</DialogDescription>
        </DialogHeader>
        <label className="sl-metric-decision-field">
          {text.reasonLabel}
          <Textarea
            value={reason}
            maxLength={2000}
            disabled={busy}
            className="min-h-24"
            onChange={event => setReason(event.target.value)}
          />
        </label>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>Huỷ</Button>
          <Button
            variant={decision === 'revoke' ? 'destructive' : 'default'}
            disabled={busy || missingReason}
            onClick={() => onConfirm(reason.trim())}
          >
            {busy ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
            {text.confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
