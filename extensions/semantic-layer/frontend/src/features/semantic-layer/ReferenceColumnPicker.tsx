import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronRight } from 'lucide-react';
import type { ReferenceDataset } from './types';

type ReferenceColumnPickerProps = {
  datasets: ReferenceDataset[];
  datasetId: number | null;
  columnName: string | null;
  disabled?: boolean;
  onChange: (datasetId: number | null, columnName: string | null) => void;
};

const MENU_WIDTH = 236;
const MENU_HEIGHT = 320;

export function ReferenceColumnPicker({
  datasets,
  datasetId,
  columnName,
  disabled = false,
  onChange,
}: ReferenceColumnPickerProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeDatasetId, setActiveDatasetId] = useState<number | null>(null);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const selectedDataset = datasets.find(dataset => dataset.id === datasetId);
  const activeDataset = datasets.find(dataset => dataset.id === activeDatasetId);

  const updatePosition = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const totalWidth = MENU_WIDTH * 2;
    setPosition({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - totalWidth - 8)),
      top: Math.max(8, Math.min(rect.top, window.innerHeight - MENU_HEIGHT - 8)),
    });
  };

  useEffect(() => {
    if (!open) return undefined;
    updatePosition();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open]);

  const toggleMenu = () => {
    if (open) {
      setOpen(false);
      return;
    }
    setActiveDatasetId(datasetId);
    updatePosition();
    setOpen(true);
  };

  return (
    <>
      <button
        ref={triggerRef}
        className="sl-reference-trigger"
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Chọn bảng và cột tham chiếu"
        onClick={toggleMenu}
        title={selectedDataset && columnName ? `${selectedDataset.label} → ${columnName}` : 'Chọn bảng và cột tham chiếu'}
      >
        <span>{selectedDataset && columnName ? `${selectedDataset.label} · ${columnName}` : 'Chọn bảng → cột'}</span>
        <ChevronRight />
      </button>
      {open && typeof document !== 'undefined' ? createPortal(
        <div
          className="sl-reference-cascade"
          ref={menuRef}
          style={{ left: position.left, top: position.top }}
        >
          <div className="sl-reference-menu" role="menu" aria-label="Chọn bảng tham chiếu">
            <div className="sl-reference-menu-heading">Bảng</div>
            <button
              className={`sl-reference-menu-item${datasetId === null ? ' is-selected' : ''}`}
              type="button"
              role="menuitem"
              onClick={() => {
                onChange(null, null);
                setOpen(false);
              }}
            >
              <span>Không tham chiếu</span>
            </button>
            <div className="sl-reference-options">
              {datasets.map(dataset => (
                <button
                  key={dataset.id}
                  className={`sl-reference-menu-item${activeDatasetId === dataset.id ? ' is-active' : ''}${datasetId === dataset.id ? ' is-selected' : ''}`}
                  type="button"
                  role="menuitem"
                  aria-haspopup="menu"
                  onClick={() => setActiveDatasetId(dataset.id)}
                >
                  <span title={dataset.label}>{dataset.label}</span>
                  <ChevronRight />
                </button>
              ))}
            </div>
          </div>
          {activeDataset ? (
            <div className="sl-reference-menu" role="menu" aria-label={`Chọn cột trong ${activeDataset.label}`}>
              <div className="sl-reference-menu-heading">Cột · {activeDataset.label}</div>
              <div className="sl-reference-options">
                {activeDataset.columns.map(name => (
                  <button
                    key={name}
                    className={`sl-reference-menu-item${datasetId === activeDataset.id && columnName === name ? ' is-selected' : ''}`}
                    type="button"
                    role="menuitemradio"
                    aria-checked={datasetId === activeDataset.id && columnName === name}
                    onClick={() => {
                      onChange(activeDataset.id, name);
                      setOpen(false);
                    }}
                  >
                    <span title={name}>{name}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>,
        document.querySelector('.sl-overlay') || document.body,
      ) : null}
    </>
  );
}
