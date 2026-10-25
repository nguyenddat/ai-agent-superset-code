import React from 'react';
import { MessageSquareText, UsersRound } from 'lucide-react';
import type { CreationRequest } from './creationRequest';

/** Names where a prefilled form came from, so the administrator can check the proposal against it. */
export function CreationOrigin({ request, children }: { request: CreationRequest; children?: React.ReactNode }) {
  if (request.kind === 'metric') {
    const { question } = request;
    return (
      <div className="sl-creation-origin">
        <MessageSquareText aria-hidden="true" />
        <div>
          <strong>Đề xuất từ câu hỏi AI Agent</strong>
          <q>{question.rewritten_question || question.question}</q>
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className="sl-creation-origin">
      <UsersRound aria-hidden="true" />
      <div>
        <strong>Khái niệm {request.userCount} người dùng đã tự định nghĩa</strong>
        {request.concept ? <q>{request.concept}</q> : null}
        <p>
          Chỉ tên và khái niệm được điền sẵn. Định nghĩa chung và ngưỡng do chuyên gia nghiệp vụ xác định, không lấy
          theo cách hiểu riêng của người dùng.
        </p>
        {children}
      </div>
    </div>
  );
}
