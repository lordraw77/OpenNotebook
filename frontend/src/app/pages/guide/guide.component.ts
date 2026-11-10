import { Component, computed, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

import { TranslatePipe, currentLang } from '../../core/i18n';
import { GUIDE } from './guide-content';

/** In-app user guide. Text and screenshots follow the interface language (screenshots: scripts/docs). */
@Component({
  selector: 'app-guide',
  imports: [MatIconModule, TranslatePipe],
  template: `
    <div class="guide">
      <nav class="toc" [attr.aria-label]="'Guide contents' | t">
        <h2>{{ 'Guide' | t }}</h2>
        @for (s of sections; track s.id) {
          <a [href]="'#' + s.id" [class.active]="active() === s.id" (click)="jump($event, s.id)">
            <mat-icon>{{ s.icon }}</mat-icon>
            <span>{{ s.title }}</span>
          </a>
        }
      </nav>
      <article class="body" (scroll)="onScroll($event)">
        <h1 class="gradient-text">{{ 'User guide' | t }}</h1>
        @for (s of sections; track s.id; let i = $index) {
          <section [id]="s.id">
            <h2>
              <span class="num">{{ i + 1 }}</span> {{ s.title }}
            </h2>
            @for (p of s.intro; track p) {
              <p>{{ p }}</p>
            }
            @if (s.steps) {
              <ol>
                @for (step of s.steps; track step) {
                  <li>{{ step }}</li>
                }
              </ol>
            }
            @if (s.tips) {
              <ul class="tips">
                @for (tip of s.tips; track tip) {
                  <li>{{ tip }}</li>
                }
              </ul>
            }
            @for (shot of s.shots ?? []; track shot.file) {
              <figure>
                <img
                  [src]="'guide/' + lang + '/' + shot.file + '.webp'"
                  [alt]="shot.alt"
                  loading="lazy"
                />
                <figcaption>{{ shot.alt }}</figcaption>
              </figure>
            }
          </section>
        }
      </article>
    </div>
  `,
  styles: `
    :host {
      display: block;
      height: 100%;
      min-height: 0;
    }
    .guide {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      height: 100%;
    }
    .toc {
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 16px 12px;
      overflow-y: auto;
      border-right: 1px solid var(--mat-sys-outline-variant, #ccc);
    }
    .toc h2 {
      margin: 0 8px 8px;
      font-size: 1.1rem;
    }
    .toc a {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 10px;
      border-radius: 10px;
      color: inherit;
      text-decoration: none;
      font-size: 0.9rem;
    }
    .toc a mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
      opacity: 0.75;
    }
    .toc a:hover,
    .toc a.active {
      background: color-mix(in srgb, var(--mat-sys-primary, #6750a4) 12%, transparent);
    }
    .body {
      overflow-y: auto;
      padding: 8px clamp(16px, 4vw, 56px) 64px;
      scroll-behavior: smooth;
    }
    .body > * {
      max-width: 920px;
    }
    h1 {
      font-size: 2rem;
      margin: 16px 0 8px;
    }
    section {
      padding-top: 24px;
      scroll-margin-top: 8px;
    }
    h2 {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 1.35rem;
      margin: 0 0 8px;
    }
    .num {
      display: inline-grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      font-size: 0.85rem;
      color: var(--mat-sys-on-primary, #fff);
      background: var(--mat-sys-primary, #6750a4);
    }
    p,
    li {
      line-height: 1.6;
    }
    .tips {
      padding: 8px 8px 8px 28px;
      border-left: 3px solid var(--mat-sys-primary, #6750a4);
      background: color-mix(in srgb, var(--mat-sys-primary, #6750a4) 7%, transparent);
      border-radius: 4px;
    }
    figure {
      margin: 16px 0;
    }
    img {
      width: 100%;
      height: auto;
      border-radius: 12px;
      border: 1px solid var(--mat-sys-outline-variant, #ccc);
      box-shadow: 0 6px 24px rgb(0 0 0 / 0.1);
    }
    figcaption {
      margin-top: 6px;
      font-size: 0.85rem;
      opacity: 0.7;
      text-align: center;
    }
    @media (max-width: 820px) {
      .guide {
        grid-template-columns: 1fr;
        grid-template-rows: auto minmax(0, 1fr);
      }
      .toc {
        flex-direction: row;
        flex-wrap: nowrap;
        overflow-x: auto;
        border-right: 0;
        border-bottom: 1px solid var(--mat-sys-outline-variant, #ccc);
      }
      .toc h2 {
        display: none;
      }
      .toc a span {
        white-space: nowrap;
      }
    }
  `,
})
export class GuideComponent {
  protected readonly lang = currentLang();
  protected readonly sections = GUIDE[this.lang];
  protected readonly active = signal(this.sections[0].id);
  private readonly offsets = computed(() => this.sections.map((s) => s.id));

  protected jump(event: Event, id: string): void {
    event.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    this.active.set(id);
  }

  protected onScroll(event: Event): void {
    const container = event.target as HTMLElement;
    let current = this.offsets()[0];
    for (const id of this.offsets()) {
      const el = document.getElementById(id);
      if (el && el.offsetTop - container.offsetTop <= container.scrollTop + 80) current = id;
    }
    this.active.set(current);
  }
}
