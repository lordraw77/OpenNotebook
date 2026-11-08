import { TestBed } from '@angular/core/testing';

import { AnswerViewComponent } from './answer-view.component';

describe('AnswerViewComponent', () => {
  it('renders citation chips without stray spaces and only for known passages', () => {
    const fixture = TestBed.createComponent(AnswerViewComponent);
    fixture.componentRef.setInput('content', 'Hold reset [S1]. Unknown [S7].');
    fixture.componentRef.setInput('citations', [
      {
        n: 1,
        source_title: 'manual.pdf',
        page_start: 4,
        page_end: 4,
        line_start: null,
        line_end: null,
      },
    ]);
    fixture.detectChanges();
    const p = fixture.nativeElement.querySelector('p') as HTMLElement;
    expect(p.textContent).toBe('Hold reset 1. Unknown .');
    expect(p.querySelectorAll('button.cite').length).toBe(1);
    expect(p.querySelector('button.cite')!.getAttribute('aria-label')).toBe(
      'Open source 1: manual.pdf, p. 4',
    );
  });
});
