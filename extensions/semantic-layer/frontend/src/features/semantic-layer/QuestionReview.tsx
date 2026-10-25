import React, { useState } from 'react';
import { DefinitionReview } from './DefinitionReview';
import { MissingMetricReview } from './MissingMetricReview';

type ReviewTab = 'definitions' | 'metrics';

/**
 * What AI Agent questions left for administrators: concepts users defined for themselves, which only signal where a
 * shared definition would help, and questions no approved metric could answer.
 */
export function QuestionReview() {
  const [tab, setTab] = useState<ReviewTab>('definitions');
  return (
    <div className="sl-question-review-page">
      <div className="sl-metrics-tabs" role="tablist" aria-label="Nội dung xử lý">
        <button type="button" role="tab" aria-selected={tab === 'definitions'} onClick={() => setTab('definitions')}>
          Cách hiểu của người dùng
        </button>
        <button type="button" role="tab" aria-selected={tab === 'metrics'} onClick={() => setTab('metrics')}>
          Thiếu metric
        </button>
      </div>
      {tab === 'definitions' ? <DefinitionReview /> : <MissingMetricReview />}
    </div>
  );
}
