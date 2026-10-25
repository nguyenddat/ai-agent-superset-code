import React, { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';

/** The wording of one review decision; only a revocation is destructive and must give a reason. */
export type ReviewDecisionText = {
  title: string;
  description: string;
  reasonLabel: string;
  confirmLabel: string;
  reasonRequired: boolean;
  destructive?: boolean;
};

type ReviewDecisionDialogProps = {
  text: ReviewDecisionText | null;
  subject: string;
  reasonMaxLength: number;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
};

/** Asks for the note or reason that the review history keeps with a propose, approve or revoke decision. */
export function ReviewDecisionDialog(
  { text, subject, reasonMaxLength, busy, onConfirm, onClose }: ReviewDecisionDialogProps,
) {
  const [reason, setReason] = useState('');
  useEffect(() => setReason(''), [text]);
  if (text === null) return null;
  const missingReason = text.reasonRequired && !reason.trim();

  return (
    <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{text.title}: {subject}</DialogTitle>
          <DialogDescription>{text.description}</DialogDescription>
        </DialogHeader>
        <label className="sl-metric-decision-field">
          {text.reasonLabel}
          <Textarea
            value={reason}
            maxLength={reasonMaxLength}
            disabled={busy}
            className="min-h-24"
            onChange={event => setReason(event.target.value)}
          />
        </label>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>Huỷ</Button>
          <Button
            variant={text.destructive ? 'destructive' : 'default'}
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
