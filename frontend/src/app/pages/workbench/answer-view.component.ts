import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { Citation, citationLocation } from '../../core/sources.api';
import { Inline, parseAnswer } from './answer-render';
import { TranslatePipe } from '../../core/i18n';

/** Renders an answer (or a note saved from the chat) with clickable citation chips. */
@Component({
  selector: 'app-answer-view',
  imports: [TranslatePipe, NgTemplateOutlet, MatTooltipModule],
  template: `
    @for (b of blocks(); track $index) {
      @switch (b.kind) {
        @case ('heading') {
          <p class="heading" [class]="'h' + b.level">
            <ng-container *ngTemplateOutlet="inl; context: { $implicit: b.inlines }" />
          </p>
        }
        @case ('paragraph') {
          <p><ng-container *ngTemplateOutlet="inl; context: { $implicit: b.inlines }" /></p>
        }
        @case ('list') {
          @if (b.ordered) {
            <ol>
              @for (item of b.items; track $index) {
                <li><ng-container *ngTemplateOutlet="inl; context: { $implicit: item }" /></li>
              }
            </ol>
          } @else {
            <ul>
              @for (item of b.items; track $index) {
                <li><ng-container *ngTemplateOutlet="inl; context: { $implicit: item }" /></li>
              }
            </ul>
          }
        }
        @case ('code') {
          <pre class="code">{{ b.text }}</pre>
        }
      }
    }
    @if (streaming()) {
      <span class="caret" aria-hidden="true"></span>
    }

    <ng-template #inl let-inlines>
      @for (s of asInlines(inlines); track $index) {
        @switch (s.kind) {
          @case ('text') {
            <span>{{ s.text }}</span>
          }
          @case ('strong') {
            <strong>{{ s.text }}</strong>
          }
          @case ('em') {
            <em>{{ s.text }}</em>
          }
          @case ('code') {
            <code>{{ s.text }}</code>
          }
          @case ('cite') {
            @let c = byNumber().get(s.n);
            @if (c) {
              <button
                type="button"
                class="cite"
                [matTooltip]="tooltip(c)"
                [attr.aria-label]="'Open source {n}: {title}' | t: { n: s.n, title: tooltip(c) }"
                (click)="cite.emit(c)"
                [textContent]="s.n"
              ></button>
            }
          }
        }
      }
    </ng-template>
  `,
  styles: `
    :host {
      display: block;
      line-height: 1.6;
      overflow-wrap: anywhere;
    }
    p {
      margin: 0 0 8px;
    }
    .heading {
      font-weight: 600;
      margin-top: 12px;
    }
    .h1,
    .h2 {
      font-size: 1.1em;
    }
    ul,
    ol {
      margin: 0 0 8px;
      padding-left: 22px;
    }
    li {
      margin: 2px 0;
    }
    code {
      font-family: ui-monospace, monospace;
      font-size: 0.9em;
      padding: 1px 4px;
      border-radius: 4px;
      background: var(--mat-sys-surface-container-highest);
    }
    .code {
      font-family: ui-monospace, monospace;
      font-size: 13px;
      padding: 10px 12px;
      border-radius: 8px;
      background: var(--mat-sys-surface-container-highest);
      overflow: auto;
      margin: 0 0 8px;
    }
    .cite {
      display: inline-grid;
      place-items: center;
      min-width: 18px;
      height: 18px;
      padding: 0 4px;
      margin: 0 0 0 2px;
      border: 0;
      border-radius: 10px;
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
      font: 600 11px/1 var(--mat-sys-label-small-font, inherit);
      vertical-align: 2px;
      cursor: pointer;
    }
    .cite:hover,
    .cite:focus-visible {
      background: var(--mat-sys-primary);
      color: var(--mat-sys-on-primary);
      outline: none;
    }
    .caret {
      display: inline-block;
      width: 8px;
      height: 1em;
      vertical-align: -2px;
      background: var(--mat-sys-primary);
      animation: blink 1s steps(2) infinite;
    }
    @keyframes blink {
      50% {
        opacity: 0;
      }
    }
  `,
})
export class AnswerViewComponent {
  readonly content = input.required<string>();
  /** Passages that markers refer to (the message context, or a note's citations). */
  readonly citations = input<Citation[]>([]);
  readonly streaming = input(false);
  readonly cite = output<Citation>();

  readonly blocks = computed(() => parseAnswer(this.content()));
  readonly byNumber = computed(() => new Map(this.citations().map((c) => [c.n, c])));

  protected asInlines(value: unknown): Inline[] {
    return value as Inline[];
  }

  protected tooltip(c: Citation): string {
    const loc = citationLocation(c);
    return `${c.source_title}${loc ? ', ' + loc : ''}`;
  }
}
