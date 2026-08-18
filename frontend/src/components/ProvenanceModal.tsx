import React from 'react';
import { X, CheckCircle2, ShieldCheck, Database, Clock, Copy, Check } from 'lucide-react';
import { ProvenanceTag } from '../types';

interface ProvenanceModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  tag?: ProvenanceTag | null;
  rawPayload?: Record<string, any> | null;
}

export const ProvenanceModal: React.FC<ProvenanceModalProps> = ({
  isOpen,
  onClose,
  title,
  tag,
  rawPayload
}) => {
  const [copied, setCopied] = React.useState(false);

  if (!isOpen || (!tag && !rawPayload)) return null;

  const handleCopy = () => {
    const content = JSON.stringify(tag || rawPayload, null, 2);
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl bg-surface border border-surface-border rounded-2xl shadow-2xl overflow-hidden glass-panel-elevated">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-border bg-surface/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white">{title}</h3>
              <p className="text-xs text-slate-400">Verifiable Mireye Geospatial Provenance Telemetry</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-surface-elevated transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5 max-h-[75vh] overflow-y-auto">
          {tag && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="p-3 rounded-xl bg-surface-elevated/60 border border-surface-border/50">
                <span className="text-xs text-slate-400 flex items-center gap-1.5 mb-1">
                  <Database className="w-3.5 h-3.5 text-cyan-400" /> Mireye Endpoint
                </span>
                <span className="font-mono text-xs text-cyan-300 font-semibold">{tag.endpoint}</span>
              </div>

              <div className="p-3 rounded-xl bg-surface-elevated/60 border border-surface-border/50">
                <span className="text-xs text-slate-400 flex items-center gap-1.5 mb-1">
                  <Clock className="w-3.5 h-3.5 text-amber-400" /> Response Hash & Latency
                </span>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-amber-300">{tag.response_hash}</span>
                  <span className="text-xs text-slate-400">{tag.latency_ms}ms ({tag.cached ? '⚡ Cached' : '🌐 Live'})</span>
                </div>
              </div>

              <div className="col-span-2 p-3 rounded-xl bg-surface-elevated/60 border border-surface-border/50">
                <span className="text-xs text-slate-400 block mb-1">Query Parameters</span>
                <pre className="font-mono text-xs text-slate-300 overflow-x-auto bg-black/40 p-2 rounded-lg">
                  {JSON.stringify(tag.params, null, 2)}
                </pre>
              </div>

              <div className="col-span-2 p-3 rounded-xl bg-surface-elevated/60 border border-surface-border/50">
                <span className="text-xs text-slate-400 block mb-1">Audit Timestamp (UTC)</span>
                <span className="font-mono text-xs text-emerald-400">{tag.timestamp}</span>
              </div>
            </div>
          )}

          {rawPayload && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Payload Data</span>
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-slate-300 hover:text-white bg-surface-elevated rounded-lg hover:bg-slate-700 transition-colors"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? 'Copied' : 'Copy JSON'}
                </button>
              </div>
              <pre className="p-4 rounded-xl bg-black/60 border border-surface-border text-xs font-mono text-emerald-300/90 overflow-x-auto">
                {JSON.stringify(rawPayload, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-3.5 bg-surface/80 border-t border-surface-border">
          <div className="flex items-center gap-2 text-xs text-emerald-400">
            <CheckCircle2 className="w-4 h-4" />
            <span>Critic Agent Verified & Immutable</span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-semibold text-white bg-surface-elevated hover:bg-slate-700 rounded-lg transition-colors"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
};
