import json,pathlib,sys,tempfile,threading,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import builder
class WriteJsonTests(unittest.TestCase):
    def test_concurrent_writers_to_one_state_file_do_not_collide(self):
        with tempfile.TemporaryDirectory() as directory:
            target=pathlib.Path(directory)/'.state'/'latest.json';errors=[]
            def write(n):
                try:
                    for i in range(50):builder.write_json(target,{'writer':n,'i':i})
                except Exception as error:errors.append(error)
            threads=[threading.Thread(target=write,args=(n,)) for n in range(4)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertEqual(errors,[])
            self.assertIn(json.loads(target.read_text())['writer'],range(4))
            self.assertEqual(list(target.parent.glob('*.tmp')),[])
if __name__=='__main__':unittest.main()
