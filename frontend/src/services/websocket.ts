import { AgentTraceEvent } from '../types';

export type TraceCallback = (event: AgentTraceEvent) => void;
export type SignalCallback = (data: any) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private traceListeners: Set<TraceCallback> = new Set();
  private signalListeners: Set<SignalCallback> = new Set();
  private reconnectTimeout: number | null = null;
  private url: string;

  constructor() {
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname || 'localhost';
    this.url = `${wsProto}//${host}:8000/ws/trace`;
  }

  public connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[OptiFlow WS] Connected to live agent trace stream.');
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'agent_trace' && payload.event) {
            this.traceListeners.forEach((fn) => fn(payload.event));
          } else if (payload.type === 'initial_trace' && Array.isArray(payload.events)) {
            payload.events.forEach((ev: AgentTraceEvent) => {
              this.traceListeners.forEach((fn) => fn(ev));
            });
          } else {
            this.signalListeners.forEach((fn) => fn(payload));
          }
        } catch (e) {
          console.error('[OptiFlow WS] Failed to parse WebSocket message:', e);
        }
      };

      this.ws.onclose = () => {
        console.warn('[OptiFlow WS] Disconnected. Reconnecting in 3s...');
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this.ws?.close();
      };
    } catch (err) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimeout) return;
    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, 3000);
  }

  public onTrace(fn: TraceCallback) {
    this.traceListeners.add(fn);
    return () => {
      this.traceListeners.delete(fn);
    };
  }

  public onSignal(fn: SignalCallback) {
    this.signalListeners.add(fn);
    return () => {
      this.signalListeners.delete(fn);
    };
  }
}

export const wsClient = new WebSocketClient();
