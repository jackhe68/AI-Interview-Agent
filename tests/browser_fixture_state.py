"""State stub for older browser tests that already replace their answer API."""
def stub_browser_state(page):
    def state(route):
        current=page.evaluate("JSON.parse(localStorage.getItem('iv-session') || '{}')")
        route.fulfill(status=200,json=dict(session_id=current.get('session_id'),
            question=current.get('question','问题'),question_sequence=current.get('question_sequence',1),
            progress=current.get('progress',dict(main=1,total=3,type='main')),
            finished=current.get('finished',False),comment=current.get('last_comment',''),
            answered_count=current.get('answered_count',0),processing=False))
    page.route('**/api/interview/*/state',state)
