import React, { useEffect, useState } from 'react';
import { AlertCircle, ExternalLink, LoaderCircle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { supersetApi } from './api';
import { GOVERNANCE_DASHBOARD_SLUG } from './constants';

const dashboardPath = `/superset/dashboard/${GOVERNANCE_DASHBOARD_SLUG}/`;

/**
 * The governance home is a Superset dashboard built by simulation/superset/bootstrap_governance.py on read-only
 * reporting views, embedded in standalone mode so its charts keep Superset's permissions, tooltips and drill-down.
 */
export function Overview() {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    fetch(supersetApi.dashboard(GOVERNANCE_DASHBOARD_SLUG), { credentials: 'same-origin' })
      .then(response => { if (active) setAvailable(response.ok); })
      .catch(() => { if (active) setAvailable(false); });
    return () => { active = false; };
  }, []);

  return (
    <div className="sl-overview">
      <div className="sl-overview-toolbar">
        <h3>Câu hỏi AI Agent</h3>
        <div className="sl-overview-actions">
          <a className="sl-overview-link" href={dashboardPath} target="_blank" rel="noreferrer">
            Mở trong Superset <ExternalLink aria-hidden="true" />
          </a>
          <Button type="button" variant="outline" size="sm" onClick={() => setReloadKey(value => value + 1)}>
            <RotateCcw /> Làm mới
          </Button>
        </div>
      </div>
      {available === null ? (
        <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải dashboard…</p>
      ) : !available ? (
        <div className="sl-metric-error" role="alert">
          <AlertCircle /> Chưa có dashboard “Tổng quan AI Agent”. Chạy lại superset-init để tạo
          (<code>docker compose up superset-init</code>).
        </div>
      ) : (
        <iframe
          key={reloadKey}
          className="sl-overview-dashboard"
          title="Tổng quan AI Agent"
          src={`${dashboardPath}?standalone=2`}
        />
      )}
    </div>
  );
}
