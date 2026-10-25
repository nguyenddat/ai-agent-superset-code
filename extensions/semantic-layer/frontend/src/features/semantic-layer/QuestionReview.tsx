import React, { useState } from 'react';
import { DatasetProposalReview } from './DatasetProposalReview';
import { DefinitionReview } from './DefinitionReview';
import { MissingMetricReview } from './MissingMetricReview';

type ReviewTab = 'definitions' | 'metrics' | 'datasets';

/**
 * What AI Agent questions left for administrators: concepts users defined for themselves, which only signal where a
 * shared definition would help, questions no approved metric could answer, and datasets the agent drafted over base
 * datasets when no aggregate dataset could answer.
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
        <button type="button" role="tab" aria-selected={tab === 'datasets'} onClick={() => setTab('datasets')}>
          Đề xuất dataset
        </button>
      </div>
      {tab === 'definitions' ? <DefinitionReview /> : tab === 'metrics' ? <MissingMetricReview /> : <DatasetProposalReview />}
    </div>
  );
}
