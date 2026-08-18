import React, { useState } from 'react';
import { Bot, Send, Sparkles, MessageSquare, ShieldCheck, HelpCircle, Loader2 } from 'lucide-react';
import { askNarrator } from '../services/api';
import { ProvenanceTag } from '../types';

interface NarratorChatProps {
  narrativeText: string;
  onInspectProvenance: (title: string, tag: ProvenanceTag, payload?: any) => void;
}

interface Message {
  sender: 'user' | 'assistant';
  text: string;
  provenance?: Record<string, ProvenanceTag>;
}

export const NarratorChat: React.FC<NarratorChatProps> = ({
  narrativeText,
  onInspectProvenance
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputQuery, setInputQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const quickPrompts = [
    'Why was Cougar Mountain rejected?',
    'Explain the Cost vs. Resilience trade-off',
    'Which warehouses are at flood risk?',
    'What if Kent South fails?'
  ];

  const handleSend = async (queryText?: string) => {
    const q = queryText || inputQuery;
    if (!q.trim() || isLoading) return;

    const userMsg: Message = { sender: 'user', text: q };
    setMessages((prev) => [...prev, userMsg]);
    setInputQuery('');
    setIsLoading(true);

    try {
      const res = await askNarrator(q);
      const botMsg: Message = {
        sender: 'assistant',
        text: res.answer,
        provenance: res.provenance
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (err: any) {
      const errorMsg: Message = {
        sender: 'assistant',
        text: `Error contacting Narrator Agent: ${err.message}`
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* 1. Executive Intelligence Narrative */}
      <div className="p-5 rounded-2xl glass-panel border border-surface-border flex flex-col h-[480px]">
        <div className="flex items-center space-x-2 border-b border-surface-border/70 pb-3 mb-3">
          <div className="p-1.5 rounded-lg bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Executive Logistics Intelligence Narrative
            </h3>
            <p className="text-[11px] text-slate-400">
              Grounded synthesis of siting, flood risk, and Pareto trade-offs
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto pr-2 space-y-3 text-xs leading-relaxed text-slate-300 font-sans">
          {narrativeText ? (
            <div className="whitespace-pre-line space-y-2">
              {narrativeText.split('\n\n').map((para, i) => (
                <div key={i} className="p-3 rounded-xl bg-surface-elevated/50 border border-surface-border/50">
                  {para}
                </div>
              ))}
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500 text-xs">
              <span>Generating executive summary...</span>
            </div>
          )}
        </div>
      </div>

      {/* 2. Interactive "What-If" AI Assistant */}
      <div className="p-5 rounded-2xl glass-panel border border-surface-border flex flex-col h-[480px]">
        <div className="flex items-center justify-between border-b border-surface-border/70 pb-3 mb-3">
          <div className="flex items-center space-x-2">
            <div className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <Bot className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                Narrator Agent "What-If" Assistant
              </h3>
              <p className="text-[11px] text-slate-400">
                Interactive inquiry backed strictly by structured state variables
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Zero Hallucination Guardrail</span>
          </div>
        </div>

        {/* Chat History */}
        <div className="flex-1 overflow-y-auto space-y-3 pr-1 text-xs">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center px-4 space-y-3">
              <HelpCircle className="w-8 h-8 text-slate-600" />
              <p>Ask free-form questions about network design, rejected sites, Pareto trade-offs, or disaster resilience.</p>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {quickPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => handleSend(prompt)}
                    className="px-2.5 py-1 text-[11px] rounded-lg bg-surface-elevated hover:bg-slate-700 text-slate-300 hover:text-white border border-surface-border transition-colors"
                  >
                    "{prompt}"
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-xl border text-xs leading-relaxed ${
                  msg.sender === 'user'
                    ? 'ml-8 bg-emerald-600/20 text-emerald-200 border-emerald-500/30'
                    : 'mr-8 bg-surface-elevated text-slate-200 border-surface-border'
                }`}
              >
                <span className="text-[10px] font-bold uppercase tracking-wider block mb-1 text-slate-400">
                  {msg.sender === 'user' ? 'You' : 'Narrator Agent'}
                </span>
                <div className="whitespace-pre-line">{msg.text}</div>
              </div>
            ))
          )}
          {isLoading && (
            <div className="flex items-center gap-2 text-xs text-cyan-400 p-3 bg-surface-elevated rounded-xl">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Querying upstream agents & Mireye provenance...</span>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="mt-3 flex items-center gap-2 pt-2 border-t border-surface-border/60">
          <input
            type="text"
            value={inputQuery}
            onChange={(e) => setInputQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Ask a what-if question (e.g. 'Why was Site A rejected?')..."
            className="flex-1 px-3.5 py-2 text-xs rounded-xl bg-surface-elevated border border-surface-border text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
          />
          <button
            onClick={() => handleSend()}
            disabled={isLoading || !inputQuery.trim()}
            className="p-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
