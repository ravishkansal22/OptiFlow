import React from 'react';
import { FileUp, X } from 'lucide-react';
import { cn } from './ui';
import { parseCoordinateFile } from '../lib/domain';
import type { CoordRow } from '../lib/domain';

export interface FileDropProps {
  /** Called with everything the file yielded. */
  onRows: (rows: CoordRow[], filename: string, badLines: number[]) => void;
  className?: string;
}

/**
 * Drop or pick a file of warehouse locations. Accepts CSV, TSV, plain text and
 * JSON; the parser works out which by looking at the content, so a mislabelled
 * extension still reads correctly.
 */
export const FileDrop: React.FC<FileDropProps> = ({ onRows, className }) => {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [over, setOver] = React.useState(false);
  const [status, setStatus] = React.useState<{ ok: boolean; text: string } | null>(null);

  const read = React.useCallback(
    async (file: File) => {
      try {
        const text = await file.text();
        const { valid, invalidLines } = parseCoordinateFile(text, file.name);
        if (!valid.length) {
          setStatus({
            ok: false,
            text: `Could not find any locations in ${file.name}. Each row needs a latitude and a longitude.`,
          });
          return;
        }
        setStatus({
          ok: true,
          text:
            `Read ${valid.length} location${valid.length === 1 ? '' : 's'} from ${file.name}` +
            (invalidLines.length
              ? ` · skipped ${invalidLines.length} row${invalidLines.length === 1 ? '' : 's'} that had no usable coordinates`
              : ''),
        });
        onRows(valid, file.name, invalidLines);
      } catch {
        setStatus({ ok: false, text: `Could not read ${file.name}.` });
      }
    },
    [onRows]
  );

  return (
    <div className={className}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) read(file);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-4 py-6 text-center transition-colors focus-ring',
          over ? 'border-accent bg-accent-soft' : 'border-strong bg-sunken hover:border-accent/50'
        )}
      >
        <FileUp className={cn('h-5 w-5', over ? 'text-accent' : 'text-faint')} />
        <p className="mt-2 text-xs font-medium text-ink">
          Drop a file here, or click to choose one
        </p>
        <p className="mt-1 text-2xs leading-relaxed text-muted">
          A spreadsheet exported as CSV, a text file, or JSON. Needs a latitude and a longitude
          per row; a name, capacity and yearly cost are optional.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.tsv,.txt,.json,text/csv,text/plain,application/json"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) read(file);
            e.target.value = '';
          }}
        />
      </div>

      {status && (
        <p
          className={cn(
            'mt-2 flex items-start gap-1.5 text-2xs leading-relaxed',
            status.ok ? 'text-accent' : 'text-danger'
          )}
        >
          {!status.ok && <X className="mt-0.5 h-3 w-3 shrink-0" />}
          {status.text}
        </p>
      )}
    </div>
  );
};
