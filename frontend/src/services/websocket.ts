import type { AgentTraceEvent } from '../types';
import { API_BASE } from './api';

export type ConnectionStatus = 'connecting' | 'open' | 'closed';

/** Non-trace control messages broadcast by the backend. */
export interface ServerSignal {
  type:
    | 'analysis_complete'
    | 'pipeline_complete'
    | 'pipeline_error'
    | 'disruption_applied'
    | 'disruption_resolved'
    | 'network_restored'
    | 'solution_switched'
    | 'state_reset'
    | string;
  [k: string]: any;
}

function resolveSocketUrl(): string {
  const base = API_BASE || window.location.origin;
  const url = new URL(base, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/ws/trace';
  url.search = '';
  return url.toString();
}

/**
 * Thin auto-reconnecting client over /ws/trace.
 * Trace events are de-duplicated by event_id, because the backend replays its
 * whole buffer as `initial_trace` on every (re)connect.
 */
class TraceSocket {
  private ws: WebSocket | null = null;
  private traceListeners = new Set<(e: AgentTraceEvent) => void>();
  private signalListeners = new Set<(s: ServerSignal) => void>();
  private statusListeners = new Set<(s: ConnectionStatus) => void>();
  private reconnectTimer: number | null = null;
  private keepAliveTimer: number | null = null;
  private backoff = 1000;
  private seen = new Set<string>();

  status: ConnectionStatus = 'closed';

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;

    this.setStatus('connecting');
    try {
      this.ws = new WebSocket(resolveSocketUrl());
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.backoff = 1000;
      this.setStatus('open');
      // The backend echoes "pong"; this keeps intermediaries from idling us out.
      this.keepAliveTimer = window.setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send('ping');
      }, 25000);
    };

    this.ws.onmessage = (evt) => {
      if (evt.data === 'pong') return;
      let payload: any;
      try {
        payload = JSON.parse(evt.data);
      } catch {
        return;
      }

      if (payload.type === 'agent_trace' && payload.event) {
        this.emitTrace(payload.event);
      } else if (payload.type === 'initial_trace' && Array.isArray(payload.events)) {
        payload.events.forEach((e: AgentTraceEvent) => this.emitTrace(e));
      } else {
        this.signalListeners.forEach((fn) => fn(payload));
      }
    };

    this.ws.onclose = () => {
      this.clearKeepAlive();
      this.setStatus('closed');
      this.scheduleReconnect();
    };

    this.ws.onerror = () => this.ws?.close();
  }

  /** Forget replayed-event history so a fresh run starts from a clean trace. */
  resetHistory() {
    this.seen.clear();
  }

  private emitTrace(event: AgentTraceEvent) {
    if (!event?.event_id || this.seen.has(event.event_id)) return;
    this.seen.add(event.event_id);
    this.traceListeners.forEach((fn) => fn(event));
  }

  private setStatus(s: ConnectionStatus) {
    this.status = s;
    this.statusListeners.forEach((fn) => fn(s));
  }

  private clearKeepAlive() {
    if (this.keepAliveTimer) window.clearInterval(this.keepAliveTimer);
    this.keepAliveTimer = null;
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 1.8, 15000);
  }

  onTrace(fn: (e: AgentTraceEvent) => void) {
    this.traceListeners.add(fn);
    return () => void this.traceListeners.delete(fn);
  }

  onSignal(fn: (s: ServerSignal) => void) {
    this.signalListeners.add(fn);
    return () => void this.signalListeners.delete(fn);
  }

  onStatus(fn: (s: ConnectionStatus) => void) {
    this.statusListeners.add(fn);
    fn(this.status);
    return () => void this.statusListeners.delete(fn);
  }
}

export const traceSocket = new TraceSocket();
