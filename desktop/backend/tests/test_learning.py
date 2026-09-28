"""Phase 2 integration tests, each with a disposable database."""
import copy
import unittest
import test_server as base_tests

class LearningTests(unittest.TestCase):
    setUp = base_tests.Tests.setUp
    tearDown = base_tests.Tests.tearDown
    api = base_tests.Tests.api
    progress = base_tests.Tests.progress

    def review(self, mode='typing', count=2, ident='review-test-0001'):
        words=self.api('GET','/api/vocabulary')['items'][:count]
        return dict(version=1,id=ident,mode=mode,scope='all',scopeName='All',wrongOnly=False,
                    startedAt=1000,updatedAt=1000,words=words,index=0,results=[],flipped=False)

    def save(self, s, expected=200):
        dbid=self.api('GET','/api/review/progress')['database_id']
        if s: s['updatedAt']+=1
        return self.api('PUT','/api/review/progress',{'database_id':dbid,'item':s},expected)

    def result(self,s,correct,answer=''):
        s['results'].append(dict(correct=correct,answer=answer,at=2000+len(s['results'])))

    def test_typing_resume_idempotent_and_wrong_queue(self):
        s=self.review(count=1); self.save(s)
        self.result(s,False,'wrong answer');self.save(s);self.save(s)
        self.assertEqual(self.api('GET','/api/learning/stats')['totals']['wrong'],1)
        self.assertEqual(self.api('GET','/api/learning/stats')['totals']['needs_review'],1)
        self.app.init_db()
        self.assertEqual(self.api('GET','/api/review/progress')['item'],s)
        detail=self.api('GET','/api/learning/session/'+s['id']);self.assertEqual(len(detail['events']),1)
        t=self.review(count=1,ident='review-correct-0002')
        self.result(t,True,'  '+t['words'][0]['english'].upper()+'  ');self.save(t)
        totals=self.api('GET','/api/learning/stats')['totals']
        self.assertEqual((totals['correct'],totals['wrong'],totals['needs_review'],totals['completed']),(1,1,0,2))

    def test_flashcard_is_separate_and_can_clear_mistakes(self):
        s=self.review('flashcard',1);self.result(s,False);s['index']=1;self.save(s)
        t=self.api('GET','/api/learning/stats')['totals'];self.assertEqual((t['forgotten'],t['wrong'],t['needs_review']),(1,0,1))
        s=self.review('flashcard',1,'flash-remember-0002');self.result(s,True);s['index']=1;self.save(s)
        t=self.api('GET','/api/learning/stats')['totals'];self.assertEqual((t['remembered'],t['correct'],t['needs_review']),(1,0,0))

    def test_reject_forged_answer_or_regressing_progress_atomically(self):
        s=self.review(); original=copy.deepcopy(s)
        self.result(s,True,'incorrect');self.save(s,400)
        self.assertEqual(self.api('GET','/api/learning/history')['total'],0)
        s['results'][0]['correct']=False;self.save(s)
        original['updatedAt']=s['updatedAt']+1;self.save(original,400)
        changed=copy.deepcopy(s);changed['results'][0]['answer']='different wrong';self.save(changed,400)
        self.assertEqual(self.api('GET','/api/review/progress')['item'],s)
        self.assertEqual(len(self.api('GET','/api/learning/session/'+s['id'])['events']),1)

    def test_match_mistakes_persist_until_review(self):
        s=self.progress();ids=s['pages'][0][:2]
        s['learning']={'id':'match-test-0001','startedAt':90,'scopeName':'All','events':[{'correct':False,'wordIds':ids,'at':95},{'correct':True,'wordIds':[ids[0]],'at':99}]}
        dbid=self.api('GET','/api/progress')['database_id'];self.api('PUT','/api/progress',{'database_id':dbid,'item':s})
        t=self.api('GET','/api/learning/stats')['totals'];self.assertEqual((t['correct'],t['wrong'],t['needs_review']),(1,1,2))
        self.assertEqual(len(self.api('GET','/api/learning/session/match-test-0001')['events']),3)

    def test_history_stopped_filter_pagination_and_deleted_word(self):
        s=self.review();self.result(s,False,'wrong');self.save(s)
        self.save(self.review('flashcard',1,'flash-new-0002'))
        detail=self.api('GET','/api/learning/session/'+s['id']);self.assertEqual(detail['item']['status'],'stopped')
        self.api('DELETE','/api/vocabulary/'+str(s['words'][0]['id']))
        self.assertEqual(self.api('GET','/api/learning/stats')['totals']['needs_review'],0)
        self.assertEqual(len(self.api('GET','/api/learning/session/'+s['id'])['events']),1)
        h=self.api('GET','/api/learning/history?mode=typing&offset=0&limit=1');self.assertEqual(h['total'],1);self.assertEqual(h['items'][0]['mode'],'typing')
        self.assertEqual(self.api('GET','/api/learning/history?offset=1&limit=1')['total'],2)
        self.api('GET','/api/learning/history?mode=bad',expected=400)

    def test_backup_v2_roundtrip_and_old_backup_compatibility(self):
        s=self.review();self.result(s,False,'wrong');self.save(s)
        before=self.api('GET','/api/learning/stats');backup=self.api('GET','/api/backup');self.assertEqual(backup['version'],3)
        self.save(None)
        preview=self.api('POST','/api/restore/preview',{'backup':backup});self.assertEqual(preview['history_count'],1)
        oldid=self.api('GET','/api/review/progress')['database_id']
        self.api('POST','/api/restore',{'backup':backup,'token':preview['token']})
        self.assertEqual(self.api('GET','/api/learning/stats'),before)
        self.assertEqual(self.api('GET','/api/review/progress')['item'],s)
        self.api('PUT','/api/review/progress',{'database_id':oldid,'item':s},409)
        backup['version']=1;backup.pop('learning');preview=self.api('POST','/api/restore/preview',{'backup':backup})
        self.api('POST','/api/restore',{'backup':backup,'token':preview['token']})
        self.assertEqual(self.api('GET','/api/learning/history')['total'],0)
        self.assertIsNone(self.api('GET','/api/review/progress')['item'])

    def test_invalid_learning_backup_is_rejected(self):
        s=self.review();self.result(s,False,'wrong');self.save(s)
        b=self.api('GET','/api/backup');b['learning']['events'][0]['mode']='flashcard'
        self.api('POST','/api/restore/preview',{'backup':b},400)
        self.assertEqual(self.api('GET','/api/learning/stats')['totals']['wrong'],1)

    def test_answer_normalization(self):
        for a,b in [("  DON'T   give up ","don’t give up"),('ＦＯＯ','foo'),(' New\nYork ','new york')]:
            self.assertEqual(self.app.clean_answer(a),self.app.clean_answer(b))
        self.assertNotEqual(self.app.clean_answer('ice-cream'),self.app.clean_answer('ice cream'))

if __name__=='__main__': unittest.main()
