 
xsdata --package ijpp ../b2b.ijpp.ijppservice.wsdl

# Cleanup
sed -i 's/\[\(.*\)\] = field/['"'\1'"'] = field/g' ijpp/b2b_ijpp_ijppservice.py
sed -i 's/@any/any/g' ijpp/b2b_ijpp_ijppservice.py
